"""News ingestion, version-aware analysis and auditable aggregates on the existing Store."""

import hashlib
import json
import logging
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from uuid import uuid4

from sqlalchemy import delete, inspect, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .news import FINBERT_REVISION, _model_lock, article_id, finbert, score_labels
from .news_providers import US_SYMBOLS, ApprovedRSS, Finnhub, LicensedAlphaVantage, ProviderError
from .store import TABLES, utcnow


def stamp(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("UTC/Zeitzone erforderlich")
    return result.astimezone(timezone.utc)


def input_text(item):
    return (item.get("title", "") + ". " + item.get("description", "")).strip()


def content_hash(item):
    return hashlib.sha256(input_text(item).encode()).hexdigest()


def normalized_title(item):
    return " ".join(re.findall(r"\w+", item.get("title", "").casefold()))


def revision_hash(item):
    return hashlib.sha256(
        json.dumps(
            {
                key: item.get(key)
                for key in (
                    "title",
                    "description",
                    "published_at",
                    "source",
                    "language",
                    "tickers",
                    "mapping_evidence",
                )
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def same_story(first, second):
    if not set(first.get("tickers", [])).intersection(second.get("tickers", [])):
        return False
    if (
        abs((stamp(first["published_at"]) - stamp(second["published_at"])).total_seconds())
        > 48 * 3600
    ):
        return False
    a, b = normalized_title(first), normalized_title(second)
    if re.findall(r"\d+(?:[.,]\d+)?", a) != re.findall(r"\d+(?:[.,]\d+)?", b):
        return False
    changed_words = set(a.split()).symmetric_difference(b.split())
    cosmetic = {
        "update",
        "updated",
        "breaking",
        "news",
        "report",
        "reports",
        "says",
        "said",
        "the",
        "a",
        "an",
    }
    if a != b and not changed_words.issubset(cosmetic):
        return False
    return bool(
        a
        and b
        and (a == b or (min(len(a), len(b)) >= 35 and SequenceMatcher(None, a, b).ratio() >= 0.93))
    )


class NewsEngine:
    def __init__(self, store, providers=None, classifier=None, clock=None):
        self.store, self.settings = store, store.settings
        self.injected_providers, self.classifier = providers, classifier
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.owner = None

    def schema_available(self):
        return inspect(self.store.engine).has_table("si_news_locks")

    @contextmanager
    def lease(self):
        if not self.schema_available():
            raise ValueError("News-Schema fehlt; explizite Migration v3 ausführen")
        table = TABLES["news_locks"]
        nonce = str(uuid4())
        now = self.clock()
        values = {
            "id": f"{self.settings.mode}:global",
            "mode": self.settings.mode,
            "created_at": (now + timedelta(minutes=30)).isoformat(),
            "payload": {"owner": nonce},
        }
        dialect_insert = (
            pg_insert if self.store.engine.dialect.name == "postgresql" else sqlite_insert
        )
        with self.store.engine.begin() as conn:
            inserted = conn.execute(dialect_insert(table).values(**values).on_conflict_do_nothing())
            acquired = inserted.rowcount == 1
            if not acquired:
                changed = conn.execute(
                    update(table)
                    .where(table.c.id == values["id"], table.c.created_at < now.isoformat())
                    .values(created_at=values["created_at"], payload=values["payload"])
                )
                acquired = changed.rowcount == 1
        if not acquired:
            raise ValueError("Ein News-/Analysejob läuft bereits; keine parallelen Abrufe")
        self.owner = nonce
        try:
            yield
        finally:
            with self.store.engine.begin() as conn:
                conn.execute(
                    delete(table).where(
                        table.c.id == values["id"], table.c.payload["owner"].as_string() == nonce
                    )
                )
            self.owner = None

    def heartbeat(self):
        if not self.owner:
            return
        table = TABLES["news_locks"]
        with self.store.engine.begin() as conn:
            result = conn.execute(
                update(table)
                .where(
                    table.c.id == f"{self.settings.mode}:global",
                    table.c.payload["owner"].as_string() == self.owner,
                )
                .values(created_at=(self.clock() + timedelta(minutes=30)).isoformat())
            )
            if result.rowcount != 1:
                raise ValueError("News-Sperre verloren; Job abgebrochen")

    def sources(self):
        if self.injected_providers is not None:
            return [
                (name, provider, list(US_SYMBOLS))
                for name, provider in self.injected_providers.items()
            ]
        settings = self.settings
        if settings.news_provider == "rss":
            result = []
            for feed in settings.news_rss_feeds[:10]:
                identity = "rss-" + hashlib.sha256(feed.get("url", "").encode()).hexdigest()[:12]
                result.append(
                    (
                        identity,
                        lambda f=feed, i=identity: ApprovedRSS(
                            f, before_request=lambda: self.reserve(i)
                        ),
                        [feed.get("ticker")]
                        if feed.get("ticker")
                        else [i["ticker"] for i in self.store.instruments()],
                    )
                )
            return result
        if settings.news_provider == "alpha_vantage":
            return [
                (
                    "alpha_vantage",
                    lambda: LicensedAlphaVantage(
                        settings.alpha_vantage_key,
                        settings.news_store_summaries,
                        before_request=lambda: self.reserve("alpha_vantage"),
                    ),
                    list(US_SYMBOLS),
                )
            ]
        return [
            (
                "finnhub",
                lambda: Finnhub(
                    settings.finnhub_key,
                    settings.news_store_summaries,
                    before_request=lambda: self.reserve("finnhub"),
                ),
                list(US_SYMBOLS),
            )
        ]

    def configured_reason(self):
        if not self.settings.news_enabled:
            return "News-Abruf deaktiviert · SI_NEWS_ENABLED=true erforderlich"
        if not self.settings.news_rights_accepted:
            return "Nutzungs-/Speicher-/Analyserechte zuerst prüfen und konfigurieren"
        if self.settings.news_provider == "finnhub" and not self.settings.finnhub_key:
            return "Finnhub API-Schlüssel fehlt"
        if self.settings.news_provider == "alpha_vantage" and not self.settings.alpha_vantage_key:
            return "Alpha-Vantage API-Schlüssel fehlt"
        if self.settings.news_provider == "rss" and not self.settings.news_rss_feeds:
            return "Kein ausdrücklich zugelassener RSS-Feed konfiguriert"
        return None

    def reserve(self, source):
        self.heartbeat()
        today = self.clock().date().isoformat()
        used = sum(row["created_at"][:10] == today for row in self.store.all("provider_calls"))
        budget = (
            min(self.settings.news_daily_budget, 25)
            if source == "alpha_vantage"
            else self.settings.news_daily_budget
        )
        if used >= budget:
            raise ProviderError(
                "daily_budget", "Lokales Tagesbudget für News-Abrufe erreicht", 86400
            )
        self.store.add("provider_calls", {"provider": source, "kind": "news_http_attempt"})

    def _status(self, identity):
        return self.store.get("provider_status", identity) or {}

    def statuses(self):
        available = self.schema_available()
        reason = self.configured_reason()
        now = self.clock()
        rows = []
        for identity, _, covered in self.sources():
            status = self._status(identity) if available else {}
            last = status.get("last_success")
            rows.append(
                {
                    "id": identity,
                    "provider": self.settings.news_provider,
                    "configured": reason is None,
                    "message": reason
                    or "Konfiguriert; Abruf erst nach tatsächlichem Erfolg bestätigt",
                    "covered_tickers": covered,
                    "last_attempt": status.get("last_attempt"),
                    "last_success": last,
                    "last_error": status.get("last_error"),
                    "next_allowed_at": status.get("next_allowed_at"),
                    "stale": not last
                    or (now - stamp(last)).total_seconds() > self.settings.news_stale_hours * 3600,
                    "received": status.get("received", 0),
                }
            )
        return {
            "providers": rows,
            "available_providers": [
                {
                    "id": "finnhub",
                    "credentials_configured": bool(self.settings.finnhub_key),
                    "coverage": list(US_SYMBOLS),
                },
                {
                    "id": "alpha_vantage",
                    "credentials_configured": bool(self.settings.alpha_vantage_key),
                    "coverage": list(US_SYMBOLS),
                },
                {
                    "id": "rss",
                    "configured_feeds": len(self.settings.news_rss_feeds),
                    "explicit_permission_required": True,
                },
            ],
            "schema_ready": available,
            "market_mode": self.settings.mode,
            "news_enabled": self.settings.news_enabled,
            "rights_confirmed": self.settings.news_rights_accepted,
            "auto_refresh": self.settings.news_auto_refresh and self.settings.allow_mutations,
            "interval_seconds": self.settings.news_interval_seconds,
            "max_cycles": self.settings.news_max_cycles,
            "scope": "Nur eigener privater Zugriff; keine Weitergabe von Providerdaten",
        }

    def ingest(self, articles):
        received, inserted, changed = 0, 0, 0
        for article in articles:
            self.heartbeat()
            received += 1
            identity = article_id(article)
            payload = article.model_dump(mode="json")
            old = self.store.get("news", identity)
            now = self.clock().isoformat()
            payload["last_updated_at"] = now
            payload["first_seen_at"] = old["first_seen_at"] if old else now
            payload["content_hash"] = content_hash(payload)
            payload["original_published_at"] = (
                old.get("original_published_at", old["published_at"])
                if old
                else payload["published_at"]
            )
            payload["input_scope"] = "title_summary" if payload["description"] else "title_only"
            modified = old and revision_hash(old) != revision_hash(payload)
            observation = (
                old.get("version_observed_at", old["first_seen_at"])
                if old and not modified
                else now
            )
            payload.update(version_observed_at=observation, version_hash=revision_hash(payload))
            if old and modified:
                old_version = {k: v for k, v in old.items() if k not in {"created_at", "id"}}
                old_version.update(
                    news_id=identity,
                    observed_at=old.get("version_observed_at") or old["first_seen_at"],
                    content_hash=content_hash(old),
                )
                changed += 1
            elif not old:
                inserted += 1
            version = {**payload, "news_id": identity, "observed_at": observation}
            revision_key = hashlib.sha256(
                (identity + payload["version_hash"] + observation).encode()
            ).hexdigest()
            # News, exact revision and mapping links commit atomically.
            with self.store.engine.begin() as conn:
                if modified:
                    self.store.add(
                        "news_revisions",
                        old_version,
                        hashlib.sha256(
                            (
                                identity + revision_hash(old_version) + old_version["observed_at"]
                            ).encode()
                        ).hexdigest(),
                        connection=conn,
                    )
                self.store.upsert_news_document("news", identity, payload, connection=conn)
                self.store.add("news_revisions", version, revision_key, connection=conn)
                for evidence in payload.get("mapping_evidence", []):
                    ticker = evidence["ticker"]
                    link_identity = identity + "-" + ticker
                    link = {
                        "news_id": identity,
                        "ticker": ticker,
                        "evidence": evidence,
                        "first_seen_at": now,
                    }
                    self.store.upsert_news_document(
                        "news_links", link_identity, link, connection=conn
                    )
        return {"received": received, "inserted": inserted, "updated": changed}

    def refresh(self, ticker=None, strict=False):
        reason = self.configured_reason()
        if reason:
            raise ValueError(reason)
        with self.lease():
            instruments = {item["ticker"]: item for item in self.store.instruments()}
            if ticker and ticker not in instruments:
                raise ValueError("Aktie nicht in der Watchlist")
            if not any(
                any(t in instruments and (not ticker or ticker == t) for t in covered)
                for _, _, covered in self.sources()
            ):
                raise ValueError("Keine bestätigte Provider-Zuordnung für die angefragte Watchlist")
            report = {
                "received": 0,
                "inserted": 0,
                "updated": 0,
                "errors": [],
                "successful_requests": 0,
            }
            for identity, factory, covered in self.sources():
                status = self._status(identity)
                now = self.clock()
                selected = [
                    instruments[t]
                    for t in covered
                    if t in instruments and (not ticker or ticker == t)
                ]
                if not selected:
                    continue
                if status.get("next_allowed_at") and stamp(status["next_allowed_at"]) > now:
                    report["errors"].append(
                        {"provider": identity, "code": "cooldown", "message": "Abrufpause aktiv"}
                    )
                    continue
                status = {
                    **status,
                    "last_attempt": now.isoformat(),
                    "next_allowed_at": (
                        now + timedelta(seconds=900 if identity.startswith("rss-") else 60)
                    ).isoformat(),
                }
                self.store.upsert_news_document("provider_status", identity, status)
                try:
                    provider = factory() if callable(factory) else factory
                    # One RSS request per feed, not once per ticker.
                    targets = selected[:1] if identity.startswith("rss-") else selected
                    total = 0
                    for instrument in targets:
                        result = self.ingest(provider.fetch(instrument))
                        for key in ("received", "inserted", "updated"):
                            report[key] += result[key]
                        total += result["received"]
                        report["successful_requests"] += 1
                        status.update(last_success=self.clock().isoformat(), received=total)
                    status.update(
                        last_success=self.clock().isoformat(), last_error=None, received=total
                    )
                except Exception as error:
                    code = error.code if isinstance(error, ProviderError) else "processing_error"
                    message = (
                        str(error)
                        if isinstance(error, ValueError)
                        else "Nachrichtenverarbeitung fehlgeschlagen"
                    )
                    report["errors"].append(
                        {"provider": identity, "code": code, "message": message}
                    )
                    status.update(
                        last_error={
                            "at": self.clock().isoformat(),
                            "code": code,
                            "message": message,
                        },
                        next_allowed_at=(
                            self.clock() + timedelta(seconds=getattr(error, "cooldown", 60))
                        ).isoformat(),
                    )
                    logging.warning("news_refresh_failed provider=%s code=%s", identity, code)
                self.store.upsert_news_document("provider_status", identity, status)
            if self.settings.finbert_enabled and report["received"]:
                report.update(self._analyze())
            self.save_aggregates()
            report["partial"] = bool(report["errors"] and report["successful_requests"])
            if strict and report["errors"] and not report["successful_requests"]:
                raise ValueError("News-Abruf fehlgeschlagen oder pausiert; Providerstatus prüfen")
            return report

    def analyze(self):
        with self.lease():
            result = self._analyze()
            self.save_aggregates()
            return result

    def _analyze(self):
        if not self.settings.finbert_enabled:
            raise ValueError("FinBERT ist deaktiviert; SI_FINBERT_ENABLED=true erforderlich")
        analyses = self.store.all("sentiments")
        known = {
            (item.get("news_id"), item.get("input_hash"), item.get("model_revision"))
            for item in analyses
        }
        pending = [
            item
            for item in self.store.all("news")
            if item.get("language") == "en"
            and (item["id"], content_hash(item), FINBERT_REVISION) not in known
        ]
        if not self.settings.news_rights_accepted and any(
            item.get("data_kind", "provider") == "provider" for item in pending
        ):
            raise ValueError(
                "Speicher-/Analyserechte für Providerdaten müssen vor der Analyse bestätigt sein"
            )
        count = 0
        for start in range(0, len(pending), self.settings.news_batch_size):
            self.heartbeat()
            batch = pending[start : start + self.settings.news_batch_size]
            with _model_lock:
                classifier = self.classifier or finbert(-1)
                outputs = classifier(
                    [input_text(item) for item in batch],
                    top_k=None,
                    truncation=True,
                    max_length=512,
                    batch_size=self.settings.news_batch_size,
                )
            if len(outputs) != len(batch):
                raise ValueError("FinBERT-Batch hat unerwartete Ergebnisanzahl")
            for item, labels in zip(batch, outputs):
                payload = {
                    **score_labels(labels),
                    "news_id": item["id"],
                    "input_hash": content_hash(item),
                    "input_scope": item.get("input_scope", "title_summary"),
                    "model_revision": FINBERT_REVISION,
                    "analyzed_at": self.clock().isoformat(),
                }
                identity = hashlib.sha256(
                    (item["id"] + payload["input_hash"] + FINBERT_REVISION).encode()
                ).hexdigest()
                self.store.add("sentiments", payload, identity)
                count += 1
        return {
            "analyzed": count,
            "unsupported": sum(item.get("language") != "en" for item in self.store.all("news")),
        }

    def items(self, as_of=None):
        now = as_of or self.clock()
        current = self.store.all("news")
        links = self.store.all("news_links")
        analyses = self.store.all("sentiments")
        versions = self.store.all("news_revisions") if as_of and self.schema_available() else []
        output = []
        for item in current:
            if (
                item.get("data_kind", "provider") == "provider"
                and not self.settings.news_rights_accepted
            ):
                continue
            if as_of:
                candidates = [
                    v
                    for v in versions
                    if v["news_id"] == item["id"] and stamp(v["observed_at"]) <= now
                ]
                if candidates:
                    version = max(candidates, key=lambda v: stamp(v["observed_at"]))
                    item = {**version, "id": item["id"]}
                elif (
                    stamp(item.get("version_observed_at") or item.get("first_seen_at", utcnow()))
                    > now
                ):
                    continue
            try:
                if stamp(item["published_at"]) > now or stamp(item["first_seen_at"]) > now:
                    continue
            except (ValueError, KeyError):
                continue
            ticker_links = [
                link
                for link in links
                if link["news_id"] == item["id"]
                and stamp(link.get("first_seen_at", link["created_at"])) <= now
            ]
            tickers = sorted(
                set(
                    item.get("tickers", [])
                    + (
                        []
                        if item.get("version_hash")
                        else [link["ticker"] for link in ticker_links]
                    )
                )
            )
            valid = [
                s
                for s in analyses
                if s.get("news_id") == item["id"]
                and s.get("input_hash") == content_hash(item)
                and s.get("model_revision") == FINBERT_REVISION
                and stamp(s["analyzed_at"]) <= now
            ]
            analysis = max(valid, key=lambda s: stamp(s["analyzed_at"])) if valid else None
            output.append(
                {
                    **item,
                    "tickers": tickers,
                    "analysis": analysis,
                    "analysis_status": "Analysiert"
                    if analysis
                    else "Sprache nicht unterstützt oder unklar"
                    if item.get("language") != "en"
                    else "Analyse ausstehend",
                    "stale": (now - stamp(item["published_at"])).total_seconds()
                    > self.settings.news_stale_hours * 3600,
                    "data_state": item["data_kind"]
                    if item.get("data_kind") in {"fixture", "demo"}
                    else "historical_provider"
                    if (now - stamp(item["published_at"])).total_seconds()
                    > self.settings.news_stale_hours * 3600
                    else "provider",
                    "mapping_evidence": item.get(
                        "mapping_evidence",
                        [link.get("evidence") for link in ticker_links if link.get("evidence")],
                    ),
                }
            )
        return sorted(
            output, key=lambda n: (n["published_at"], n["first_seen_at"], n["id"]), reverse=True
        )

    def aggregate(self, ticker, days=7, as_of=None):
        now = as_of or self.clock()
        cutoff = now - timedelta(days=days)
        rows = [
            row
            for row in self.items(as_of)
            if ticker in row["tickers"] and row.get("data_kind", "provider") == "provider"
        ]
        rows.sort(key=lambda row: (row["first_seen_at"], row["published_at"], row["id"]))
        groups = []
        for item in rows:
            matched = next((group for group in groups if same_story(item, group[0])), None)
            if matched is not None:
                matched.append(item)
            else:
                groups.append([item])
        representatives, included, excluded = [], [], []
        for group in groups:
            representative = group[0]
            if not (
                cutoff <= stamp(representative["published_at"]) <= now
                and cutoff <= stamp(representative["first_seen_at"]) <= now
            ):
                continue
            representatives.append(representative)
            selected = next((item for item in group if item["analysis"]), None)
            if selected:
                included.append(selected)
            excluded.extend(
                item["id"] for item in group if item is not (selected or representative)
            )
        counts = {
            label: sum(item["analysis"]["dominant"] == label for item in included)
            for label in ("positive", "negative", "neutral")
        }
        scores = [item["analysis"]["sentiment"] for item in included]
        buckets = {}
        for item in included:
            day = stamp(item["first_seen_at"]).date().isoformat()
            buckets.setdefault(day, []).append(item["analysis"]["sentiment"])
        basis = {
            "rule": "m3-v1-equal-story-weight",
            "as_of": now.isoformat(),
            "days": days,
            "news_ids": [item["id"] for item in included],
            "analysis_ids": [item["analysis"]["id"] for item in included],
            "excluded_duplicate_ids": excluded,
            "time_basis": "published_at AND first_seen_at AND analyzed_at <= as_of",
        }
        return {
            "ticker": ticker,
            "days": days,
            "as_of": now.isoformat(),
            "relevant_count": len(representatives),
            "analyzed_count": len(included),
            "duplicate_count": len(excluded),
            **counts,
            "mean_sentiment": sum(scores) / len(scores) if scores else None,
            "last_news_at": max((item["published_at"] for item in representatives), default=None),
            "latest_first_seen_at": max(
                (item["first_seen_at"] for item in representatives), default=None
            ),
            "low_sample": len(included) < 5,
            "warning": "Tonalität, keine Kursprognose; kleine Stichprobe"
            if len(included) < 5
            else "Tonalität, keine Kursprognose",
            "trend": [
                {"date": day, "count": len(values), "mean_sentiment": sum(values) / len(values)}
                for day, values in sorted(buckets.items())
            ],
            "basis": basis,
            "basis_hash": hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest(),
        }

    def save_aggregates(self):
        for instrument in self.store.instruments():
            for days in (1, 7, 30):
                payload = self.aggregate(instrument["ticker"], days)
                self.store.upsert_news_document(
                    "news_aggregates", f"{instrument['ticker']}:{days}", payload
                )
