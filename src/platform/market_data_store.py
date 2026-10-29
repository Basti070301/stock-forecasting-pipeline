"""Append-only observations in the existing Store database; explicit additive v4 migration."""

from uuid import uuid4

import pandas as pd
from sqlalchemy import MetaData, inspect, select

from .forecast_contract import SourceProvenance, prepare_snapshot, utc_now
from .market_data_provider import INSTRUMENTS, MarketDataError, canonical, checksum, stamp
from .market_data_quality import inspect_receipt
from .store import TABLES, document_table

market_metadata = MetaData()
for name in ("market_runs", "market_observations", "price_revisions"):
    TABLES.setdefault(name, document_table("si_" + name, market_metadata))


class MarketRepository:
    def __init__(self, store, clock=utc_now):
        self.store, self.clock = store, clock

    def migrated(self):
        return (
            all(
                inspect(self.store.engine).has_table(t.name)
                for t in market_metadata.tables.values()
            )
            and self.store.get("schema_versions", "v4") is not None
        )

    def migrate(self):
        if not inspect(self.store.engine).has_table("si_schema_versions"):
            raise MarketDataError(
                "schema", "Zuerst vorhandene Plattformmigration ausdrücklich ausführen"
            )
        with self.store.engine.begin() as conn:
            market_metadata.create_all(conn)
            self.store.add(
                "schema_versions",
                {"version": 4, "description": "Append-only daily observations and revisions"},
                "v4",
                connection=conn,
            )

    def event(self, kind, **fields):
        identity = str(uuid4())
        self.store.add("market_runs", {"kind": kind, "at": stamp(self.clock()), **fields}, identity)
        return identity

    def acquire(self):
        identity, owner = f"{self.store.settings.mode}:market:yfinance", str(uuid4())
        table = TABLES["news_locks"]
        with self.store.engine.begin() as conn:
            self.store.add(
                "news_locks",
                {"owner": owner, "purpose": "market:yfinance"},
                "market:yfinance",
                connection=conn,
            )
            row = conn.execute(select(table.c.payload).where(table.c.id == identity)).scalar_one()
            if row["owner"] != owner:
                raise MarketDataError("busy", "Ein Tageskurslauf hält bereits die Datenbank-Sperre")
        return owner

    def release(self, owner):
        table = TABLES["news_locks"]
        with self.store.engine.begin() as conn:
            row = conn.execute(
                select(table.c.payload).where(
                    table.c.id == f"{self.store.settings.mode}:market:yfinance"
                )
            ).scalar_one_or_none()
            if row and row["owner"] == owner:
                conn.execute(
                    table.delete().where(
                        table.c.id == f"{self.store.settings.mode}:market:yfinance"
                    )
                )

    def persist(self, receipt):
        try:
            frame, quality = inspect_receipt(receipt)
        except MarketDataError as error:
            frame = pd.DataFrame()
            quality = {
                "version": "daily-quality-v1",
                "status": "rejected",
                "issues": [{"code": error.code, "severity": "error", "row": None}],
                "received_rows": None,
                "accepted_rows": 0,
                "missing_sessions": [],
                "stale": True,
            }
        body = receipt.model_dump(mode="json")
        identity = str(receipt.receipt_id)
        fingerprint = checksum(canonical(body))
        old = self.store.get("market_observations", identity)
        if old and old["receipt_sha256"] != fingerprint:
            raise MarketDataError(
                "immutable_conflict", "Beobachtungs-ID ist mit anderem Inhalt belegt"
            )
        if pd.Timestamp(self.clock()) < pd.Timestamp(receipt.received_at):
            raise MarketDataError(
                "future_receipt", "Empfang liegt nach dem lokalen Speicherzeitpunkt"
            )
        links, new_versions = [], 0
        with self.store.engine.begin() as conn:
            observation_table = TABLES["market_observations"]
            previous = conn.execute(
                select(observation_table.c.payload).where(
                    observation_table.c.id == f"{self.store.settings.mode}:{identity}"
                )
            ).scalar_one_or_none()
            if previous and previous["receipt_sha256"] != fingerprint:
                raise MarketDataError(
                    "immutable_conflict", "Beobachtungs-ID ist mit anderem Inhalt belegt"
                )
            for row in frame.to_dict("records"):
                day = pd.Timestamp(row["trade_date"]).date().isoformat()
                bar = {k: v for k, v in row.items() if k not in {"trade_date", "ticker"}}
                # Cleaner returns only finite native OHLCV numbers. Dates are part of the revision key.
                content = {
                    "provider": receipt.provider,
                    "source_kind": receipt.source_kind,
                    "ticker": receipt.ticker,
                    "trade_date": day,
                    "adjustment": receipt.adjustment,
                    "bar": bar,
                }
                revision = checksum(canonical(content))
                table = TABLES["price_revisions"]
                present = conn.execute(
                    select(table.c.id).where(table.c.id == f"{self.store.settings.mode}:{revision}")
                ).first()
                if not present:
                    new_versions += 1
                self.store.add("price_revisions", content, revision, connection=conn)
                links.append({"trade_date": day, "revision_id": revision})
            self.store.add(
                "market_observations",
                {
                    **body,
                    "receipt_sha256": fingerprint,
                    "payload_sha256": receipt.payload_sha256,
                    "instrument": INSTRUMENTS[receipt.ticker],
                    "quality": quality,
                    "bar_links": links,
                },
                identity,
                connection=conn,
            )
            persisted = conn.execute(
                select(observation_table.c.payload).where(
                    observation_table.c.id == f"{self.store.settings.mode}:{identity}"
                )
            ).scalar_one()
            if persisted["receipt_sha256"] != fingerprint:
                raise MarketDataError(
                    "immutable_conflict",
                    "Gleichzeitige Beobachtung mit abweichendem Inhalt; Transaktion verworfen",
                )
        # Only committed data may be published. A crash before this marker leaves a quarantined,
        # unpublished receipt. This post-commit timestamp is deliberately conservative.
        available = stamp(self.clock())
        if available < stamp(receipt.received_at):
            raise MarketDataError(
                "clock",
                "Speicherbestätigung liegt vor dem Datenempfang; Beobachtung bleibt unveröffentlicht",
            )
        marker = self.store.get("market_runs", "commit:" + identity)
        if marker is None:
            self.store.add(
                "market_runs",
                {
                    "kind": "receipt_commit",
                    "receipt_id": identity,
                    "available_at": available,
                    "at": available,
                },
                "commit:" + identity,
            )
        return {
            "receipt_id": identity,
            "source_kind": receipt.source_kind,
            "new_revisions": new_versions,
            "new_observation": old is None,
            "quality": quality,
        }

    def observations(self, ticker, as_of):
        cutoff = stamp(as_of)
        commits = {
            r["receipt_id"]: r
            for r in self.store.all("market_runs")
            if r["kind"] == "receipt_commit" and r["available_at"] <= cutoff
        }
        return sorted(
            [
                {**r, "available_at": commits[r["id"]]["available_at"]}
                for r in self.store.all("market_observations")
                if r["ticker"] == ticker
                and r["id"] in commits
                and stamp(r["received_at"]) <= cutoff
            ],
            key=lambda r: (stamp(r["received_at"]), stamp(r["request_started_at"]), r["id"]),
        )

    def history(self, ticker, as_of):
        observations = self.observations(ticker, as_of)
        if not observations:
            raise MarketDataError(
                "unavailable", "Keine damals empfangene und bestätigt gespeicherte Kursbeobachtung"
            )
        receipt = observations[-1]
        tied = [r for r in observations if stamp(r["received_at"]) == stamp(receipt["received_at"])]
        if len({(r["payload_sha256"], r["source_kind"], r["adjustment"]) for r in tied}) > 1:
            raise MarketDataError(
                "ambiguous_observation",
                "Gleichzeitige abweichende Beobachtungen haben keine belegbare Reihenfolge; erneuten kontrollierten Abruf durchführen",
            )
        if receipt["quality"]["status"] != "accepted":
            raise MarketDataError(
                "quality", "Neueste verfügbare Beobachtung verletzt die Datenqualität"
            )
        # Select one whole adjustment vintage, never stitch together different provider histories.
        rows = []
        for link in receipt["bar_links"]:
            revision = self.store.get("price_revisions", link["revision_id"])
            rows.append(
                {
                    "ticker": ticker,
                    "trade_date": pd.Timestamp(link["trade_date"]),
                    **revision["bar"],
                }
            )
        return pd.DataFrame(rows).sort_values("trade_date").reset_index(drop=True), receipt

    def revisions(self, ticker, as_of):
        events = self.observations(ticker, as_of)
        versions = {}
        for event in events:
            for link in event["bar_links"]:
                key = link["revision_id"]
                entry = versions.setdefault(
                    key,
                    {
                        **self.store.get("price_revisions", key),
                        "first_seen_at": event["received_at"],
                        "last_seen_at": event["received_at"],
                        "first_available_at": event["available_at"],
                        "observations": 0,
                    },
                )
                entry["first_seen_at"] = min(
                    entry["first_seen_at"], event["received_at"], key=stamp
                )
                entry["last_seen_at"] = max(entry["last_seen_at"], event["received_at"], key=stamp)
                entry["first_available_at"] = min(
                    entry["first_available_at"], event["available_at"]
                )
                entry["observations"] += 1
        return sorted(versions.values(), key=lambda r: (r["trade_date"], r["first_seen_at"]))

    def feature_snapshot(self, ticker, decision_at):
        """Prepare the six existing features only. No model loading or forecast persistence."""
        frame, receipt = self.history(ticker, decision_at)
        if receipt["source_kind"] != "provider":
            raise MarketDataError("fixture", "Testdaten sind keine aktuelle Provider-Datenbasis")
        if receipt["declared_delay_seconds"] is None:
            raise MarketDataError(
                "delay_unknown",
                "Providerverzögerung muss vor aktueller Feature-Nutzung geprüft werden",
            )
        source = SourceProvenance(
            name="yfinance:" + receipt["id"],
            kind="stored_market_data",
            observed_at=receipt["available_at"],
            snapshot_hashes={
                "payload": receipt["payload_sha256"],
                "receipt": receipt["receipt_sha256"],
            },
        )
        return prepare_snapshot(
            frame,
            INSTRUMENTS[ticker],
            source,
            decision_at=decision_at,
            delay_seconds=max(900, receipt["declared_delay_seconds"]),
            clock=self.clock,
        )
