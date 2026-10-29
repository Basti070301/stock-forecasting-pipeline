"""Evidence-gated current research pairs. No training, model promotion or trading."""

import json
from datetime import timedelta
from uuid import uuid4

import exchange_calendars as xcals
import pandas as pd

from src.config import PROJECT_ROOT

from .forecast_contract import (
    ForecastError,
    SourceProvenance,
    latest_available_session,
    utc,
    utc_now,
)
from .market_data import MarketIngestion
from .market_data_provider import INSTRUMENTS, MarketDataError, YahooDailyProvider, checksum, stamp
from .market_data_store import MarketRepository
from .model_artifacts import canonical_hash, file_hash
from .research_forecasts import (
    ForecastRequest,
    ResearchForecastEngine,
    immutable_documents,
    record_outcome,
)

PROTOCOL_PATH = PROJECT_ROOT / "reports/research/m4_2_prospective_protocol_v1.json"
PROTOCOL_SHA256 = "9d9aaf888b02e09206c9d7a83c10e9b53da351296ffd8c40d3ee2c400e32a272"


class CurrentForecastPipeline:
    @staticmethod
    def failure_message(code):
        return {
            "unavailable": "Keine rechtzeitig gespeicherten aktuellen Kurse vorhanden",
            "missing_prices": "Vollständige OHLCV-Kurse fehlen",
            "quality": "Datenqualitätsprüfung fehlgeschlagen",
            "stale_data": "Kursdaten sind veraltet",
            "incomplete_features": "Die sechs Features sind unvollständig oder nicht endlich",
            "window_closed": "Zielsitzung bereits geöffnet; kein rückwirkendes Nachholen",
            "outcome_revision": "Outcome durch geänderte Preis-/Adjustierungsbasis gesperrt",
            "outcome_not_available": "Abgeschlossener und tatsächlich beobachteter Zielkurs fehlt",
            "attempt_budget": "Versuchslimit dieser Sitzung erreicht",
        }.get(code, "Verarbeitung kontrolliert abgelehnt: " + code)

    def __init__(
        self, store, *, clock=utc_now, repository=None, fixture_mode=False, test_protocol=None
    ):
        self.store, self.clock, self.fixture_mode = store, clock, fixture_mode
        self.settings = store.settings
        self.market = MarketRepository(store, clock)
        self.engine = ResearchForecastEngine(store, repository=repository, clock=clock)
        if test_protocol is not None and not fixture_mode:
            raise ForecastError(
                "protocol", "Testprotokoll nur in ausdrücklich isoliertem Fixturebetrieb"
            )
        if file_hash(PROTOCOL_PATH) != PROTOCOL_SHA256:
            raise ForecastError("protocol", "Eingefrorenes Protokoll wurde verändert")
        self.protocol = test_protocol or json.loads(PROTOCOL_PATH.read_text())
        self.protocol_hash = canonical_hash(test_protocol) if test_protocol else PROTOCOL_SHA256

    def gate(self, *, verification=False):
        if self.settings.historical_preview:
            raise ForecastError(
                "historical_preview",
                "Historischer Docker-Test: Current-Jobs und Provideraktivierung gesperrt",
            )
        if not self.settings.allow_mutations:
            raise ForecastError("read_only", "Leseprofil: Current-Jobs und Scheduler gesperrt")
        if not self.settings.research_trust_local_artifacts:
            raise ForecastError("trust_required", "Vertrauen in lokale Modellartefakte fehlt")
        if not self.market.migrated():
            raise ForecastError("schema", "Explizite Tagesdatenmigration v4 fehlt")
        if self.fixture_mode:
            return
        if YahooDailyProvider(self.settings).configured_reason():
            raise ForecastError(
                "provider_blocked", "Erlaubter Marktdatenzugang ist nicht bestätigt"
            )
        if self.settings.market_delay_seconds is None:
            raise ForecastError("delay_unknown", "Belegte Providerverzögerung fehlt")
        if verification:
            return
        if not self.settings.current_enabled:
            raise ForecastError(
                "current_disabled", "Current Research ist standardmäßig deaktiviert"
            )
        acceptance = (
            self.store.get("market_runs", self.settings.current_acceptance_id)
            if self.settings.current_acceptance_id
            else None
        )
        if (
            not acceptance
            or acceptance.get("kind") != "current_acceptance"
            or acceptance.get("protocol_hash") != self.protocol_hash
            or acceptance.get("rights_reference_sha256")
            != checksum(self.settings.market_rights_reference)
            or acceptance.get("declared_delay_seconds") != self.settings.market_delay_seconds
        ):
            raise ForecastError(
                "acceptance_required",
                "Lokale Provider-/E2E-Abnahme für dieses Protokoll und diesen Zugang fehlt",
            )
        if utc(acceptance["accepted_at"]) > utc(self.clock()):
            raise ForecastError("acceptance_required", "Abnahmezeit liegt in der Zukunft")

    def event(self, identity, payload):
        body = {**payload, "input_fingerprint": canonical_hash(payload)}
        self.store.add("market_runs", body, identity)
        saved = self.store.get("market_runs", identity)
        if saved["input_fingerprint"] != body["input_fingerprint"]:
            raise ForecastError("input_conflict", "Laufereignis ist unveränderlich")
        return saved

    def plan(self, ticker, now=None):
        if ticker not in self.protocol["universe"]:
            raise ForecastError("unknown_instrument", "Aktie gehört nicht zum fixierten Universum")
        now = utc(now or self.clock())
        delay = max(900, self.settings.market_delay_seconds or 0)
        cal = xcals.get_calendar(INSTRUMENTS[ticker]["calendar"])
        session = latest_available_session(INSTRUMENTS[ticker]["calendar"], now, delay)
        target = cal.next_session(session)
        opening = cal.session_open(target)
        if now >= opening:
            raise ForecastError(
                "window_closed", "Nach Öffnung der Zielsitzung keine nachgeholte Current-Prognose"
            )
        return {
            "ticker": ticker,
            "session": session.date().isoformat(),
            "target_session": target.date().isoformat(),
            "target_open": stamp(opening),
            "slot": "current:"
            + canonical_hash([self.protocol_hash, ticker, session.date().isoformat()]),
        }

    def source(self, ticker, decision_at):
        prices, receipt = self.market.history(ticker, decision_at)
        if receipt["source_kind"] != ("fixture" if self.fixture_mode else "provider"):
            raise ForecastError(
                "source_kind", "Datenherkunft passt nicht zum ausdrücklich gewählten Betriebsmodus"
            )
        if (
            receipt["provider"] != "yfinance"
            or receipt["declared_delay_seconds"] is None
            or receipt["declared_delay_seconds"] != self.settings.market_delay_seconds
        ):
            raise ForecastError(
                "delay_unknown", "Provider-/Verzögerungsvertrag der Receipt ist nicht bestätigt"
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
        return prices, receipt, source

    def paired_documents(self, ticker, decision_at, *, verification=False):
        plan = self.plan(ticker, decision_at)
        prices, receipt, source = self.source(ticker, decision_at)
        documents = []
        self.engine.inputs = lambda request: (prices, INSTRUMENTS, source)
        for fixed in self.protocol["models"]:
            request = ForecastRequest(
                artifact_id=fixed["artifact_id"],
                model_version=fixed["model_version"],
                ticker=ticker,
                mode="current",
                decision_at=decision_at,
            )
            meta, snapshot, _ = prepared = self.engine.prepare(request)
            if (
                meta.status != "research_only"
                or meta.forecast_enabled
                or meta.training_positive_rate != fixed["training_positive_rate"]
                or file_hash(self.engine.repository.path(meta.artifact_id) / "metadata.json")
                != fixed["metadata_sha256"]
                or file_hash(self.engine.repository.path(meta.artifact_id) / "model.joblib")
                != fixed["artifact_sha256"]
            ):
                raise ForecastError(
                    "protocol_model", "Modell passt nicht zum eingefrorenen Protokoll"
                )
            if receipt["declared_delay_seconds"] > snapshot.publication_delay_seconds:
                # Engine's frozen training delay must not weaken the current provider delay.
                from .forecast_contract import prepare_snapshot

                snapshot = prepare_snapshot(
                    prices,
                    INSTRUMENTS[ticker],
                    source,
                    decision_at=decision_at,
                    delay_seconds=max(900, receipt["declared_delay_seconds"]),
                    clock=self.clock,
                )
                # Engine fingerprint must be rebuilt using the stronger snapshot contract.
                fingerprint = canonical_hash(
                    {
                        "request": request.model_dump(mode="json"),
                        "snapshot": snapshot.model_dump(mode="json", exclude={"prepared_at"}),
                        "model_version": meta.model_version,
                        "metadata_sha256": canonical_hash(meta.model_dump(mode="json")),
                        "artifact_sha256": fixed["artifact_sha256"],
                    }
                )
                prepared = meta, snapshot, fingerprint
            if snapshot.feature_as_of.isoformat() != plan["session"]:
                raise ForecastError(
                    "stale_data", "Receipt entspricht nicht der geplanten abgeschlossenen Sitzung"
                )
            built = self.engine.prediction_documents(request, prepared)
            for name, identity, payload in built:
                if name == "forecasts":
                    extra = {
                        "pipeline_slot": plan["slot"],
                        "protocol_hash": self.protocol_hash,
                        "evaluation_scope": "fixture"
                        if self.fixture_mode
                        else "provider_validation"
                        if verification
                        else "prospective_candidate",
                        "source_kind": receipt["source_kind"],
                        "market_receipt_id": receipt["id"],
                        "market_first_session": str(prices.trade_date.min().date()),
                        "baseline_prevalence": meta.training_positive_rate,
                        "baseline_majority": int(meta.training_positive_rate >= 0.5),
                    }
                    payload = {
                        **payload,
                        **extra,
                        "input_fingerprint": canonical_hash(
                            {"engine": payload["input_fingerprint"], "pipeline": extra}
                        ),
                    }
                documents.append((name, identity, payload))
        if len([d for d in documents if d[0] == "forecasts"]) != 2:
            raise ForecastError("paired_models", "Genau zwei fixierte Modelle erforderlich")
        self.check_deadline(documents, plan)
        return documents, plan

    def check_deadline(self, documents, plan):
        now = utc(self.clock())
        for name, _, payload in documents:
            if name != "forecasts":
                continue
            if (
                now >= utc(plan["target_open"])
                or now - utc(payload["decision_at"]) > pd.Timedelta(seconds=300)
                or utc(payload["generated_at"]) > now
            ):
                raise ForecastError(
                    "late_forecast",
                    "Ausführung/Speicherung liegt außerhalb des eingefrorenen Zeitfensters",
                )

    def confirm_pair(self, plan, rows):
        documents = [("forecasts", r["id"], r) for r in rows]
        try:
            self.check_deadline(documents, plan)
            status = "fixture" if self.fixture_mode else "confirmed"
        except ForecastError:
            status = "late_unconfirmed"
        marker = self.event(
            plan["slot"],
            {
                "kind": "current_pair_commit",
                "slot": plan["slot"],
                "ticker": plan["ticker"],
                "feature_session": plan["session"],
                "forecast_ids": sorted(r["id"] for r in rows),
                "decision_at": rows[0]["decision_at"],
                "saved_at": stamp(self.clock()),
                "source_kind": rows[0]["source_kind"],
                "acceptance_id": self.settings.current_acceptance_id
                if not self.fixture_mode
                else None,
                "protocol_hash": self.protocol_hash,
                "status": status,
            },
        )
        if status == "late_unconfirmed":
            raise ForecastError(
                "late_forecast",
                "Daten gespeichert, aber zu spät bestätigt; keine prospektive Aufnahme",
            )
        return marker

    def run_ticker(self, ticker):
        self.gate()
        plan = self.plan(ticker)
        marker = self.store.get("market_runs", plan["slot"])
        if marker:
            return {
                "ticker": ticker,
                "status": marker["status"],
                "reused": True,
                "forecast_ids": marker["forecast_ids"],
            }
        rows = [f for f in self.store.all("forecasts") if f.get("pipeline_slot") == plan["slot"]]
        if rows:
            if len(rows) != 2 or len({r["decision_at"] for r in rows}) != 1:
                raise ForecastError(
                    "partial_pair", "Unvollständiges Paar; keine nachträgliche Ergänzung"
                )
            marker = self.confirm_pair(plan, rows)
            return {
                "ticker": ticker,
                "status": marker["status"],
                "reused": True,
                "forecast_ids": marker["forecast_ids"],
            }
        attempts = [
            r
            for r in self.store.all("market_runs")
            if r.get("kind") == "current_attempt" and r.get("slot") == plan["slot"]
        ]
        if len(attempts) >= self.settings.current_session_attempts:
            raise ForecastError(
                "attempt_budget", "Begrenzte Versuche dieser Sitzung sind ausgeschöpft"
            )
        self.market.event(
            "current_attempt", slot=plan["slot"], ticker=ticker, protocol_hash=self.protocol_hash
        )
        decision = self.clock()  # Never accept a client-supplied/backfilled decision timestamp.
        documents, plan = self.paired_documents(ticker, decision)
        # Existing immutable transaction: both models and both predictions succeed or none do.
        immutable_documents(self.store, documents)
        rows = [
            self.store.get("forecasts", identity)
            for name, identity, _ in documents
            if name == "forecasts"
        ]
        marker = self.confirm_pair(plan, rows)
        return {
            "ticker": ticker,
            "status": marker["status"],
            "reused": False,
            "forecast_ids": marker["forecast_ids"],
        }

    def refresh(self, tickers):
        if self.fixture_mode:
            raise ForecastError(
                "fixture_fetch", "Fixturebetrieb darf keine Provideraufrufe ausführen"
            )
        reports = []
        now = utc(self.clock())
        pending = [
            f
            for f in self.store.all("forecasts")
            if f.get("protocol_hash") == self.protocol_hash
            and f.get("source_kind") == "provider"
            and not self.store.get("outcomes", f["id"])
        ]
        for ticker in tickers:
            plan = self.plan(ticker, now)
            start = now.date() - timedelta(days=365)
            for row in pending:
                if row["ticker"] == ticker:
                    original_start = pd.Timestamp(row["market_first_session"]).date()
                    if (pd.Timestamp(plan["session"]).date() - original_start).days <= 732:
                        start = min(start, original_start)
                    else:
                        # Preserve the unresolved forecast without starving all future sessions.
                        self.market.event(
                            "current_history_limit", forecast_id=row["id"], ticker=ticker
                        )
            reports.append(
                MarketIngestion(
                    self.market, YahooDailyProvider(self.settings), clock=self.clock
                ).run([ticker], start, pd.Timestamp(plan["session"]).date())
            )
        return reports

    def run(self, tickers=None, *, refresh=False):
        self.gate()
        tickers = list(self.protocol["universe"] if tickers is None else tickers)
        if (
            not tickers
            or len(set(tickers)) != len(tickers)
            or not set(tickers).issubset(self.protocol["universe"])
        ):
            raise ForecastError(
                "unknown_instrument", "Eindeutige Auswahl aus dem fixierten Universum erforderlich"
            )
        with self.engine.lease("current-pipeline"):
            reports, eligible = [], []
            for ticker in tickers:
                try:
                    self.plan(ticker)
                    eligible.append(ticker)
                except ForecastError as error:
                    reports.append(
                        {
                            "ticker": ticker,
                            "status": "blocked",
                            "code": error.code,
                            "message": self.failure_message(error.code),
                        }
                    )
            refresh_report = self.refresh(eligible) if refresh and eligible else []
            outcomes = self.outcomes()
            for ticker in eligible:
                try:
                    reports.append(self.run_ticker(ticker))
                except (ForecastError, MarketDataError) as error:
                    reports.append(
                        {
                            "ticker": ticker,
                            "status": "blocked",
                            "code": error.code,
                            "message": self.failure_message(error.code),
                        }
                    )
            result = {
                "status": "completed"
                if all(r["status"] in {"confirmed", "fixture"} for r in reports)
                else "partial"
                if any(r["status"] in {"confirmed", "fixture"} for r in reports)
                else "blocked",
                "source_kind": "fixture" if self.fixture_mode else "provider",
                "results": reports,
                "refresh": refresh_report,
                "outcomes": outcomes,
            }
            if (
                refresh_report
                and any(r.get("status") != "success" for r in refresh_report)
                and result["status"] == "completed"
            ):
                result["status"] = "partial"
            if any(r["status"] == "blocked" for r in outcomes) and result["status"] == "completed":
                result["status"] = "partial"
            result["partial"] = result["status"] == "partial"
            self.market.event("current_cycle", protocol_hash=self.protocol_hash, result=result)
            return result

    def job(self, tickers=None, *, refresh=False):
        result = self.run(tickers, refresh=refresh)
        if result["status"] == "blocked":
            messages = sorted(
                {
                    r.get("message", self.failure_message(r.get("code", r["status"])))
                    for r in result["results"]
                }
            )
            raise ForecastError(
                "current_job_blocked",
                "Kein aktuelles Research-Paar erfolgreich bestätigt. " + "; ".join(messages),
            )
        return result

    def outcomes(self):
        results = []
        for forecast in self.store.all("forecasts"):
            if forecast.get("protocol_hash") != self.protocol_hash or forecast.get(
                "source_kind"
            ) != ("fixture" if self.fixture_mode else "provider"):
                continue
            cal = xcals.get_calendar(forecast["calendar"])
            due = cal.session_close(pd.Timestamp(forecast["target_session"])) + pd.Timedelta(
                seconds=forecast["publication_delay_seconds"]
            )
            marker = self.store.get("market_runs", forecast["pipeline_slot"])
            if (
                not marker
                or marker["status"] not in {"confirmed", "fixture"}
                or utc(self.clock()) < due
            ):
                continue
            try:
                prices, receipt, source = self.source(forecast["ticker"], self.clock())
                if (
                    utc(marker["saved_at"])
                    >= cal.session_open(pd.Timestamp(forecast["target_session"]))
                    or utc(receipt["received_at"]) < due
                    or utc(receipt["available_at"]) < due
                ):
                    raise ForecastError(
                        "outcome_not_available",
                        "Forecast oder Zielkurs nicht rechtzeitig tatsächlich beobachtet",
                    )
                prices = prices[prices.trade_date >= pd.Timestamp(forecast["market_first_session"])]
                original_receipt = self.store.get(
                    "market_observations", forecast["market_receipt_id"]
                )
                current_links = {r["trade_date"]: r["revision_id"] for r in receipt["bar_links"]}
                if not original_receipt or any(
                    current_links.get(r["trade_date"]) != r["revision_id"]
                    for r in original_receipt["bar_links"]
                    if r["trade_date"] <= forecast["feature_as_of"]
                ):
                    raise ForecastError(
                        "outcome_revision",
                        "Adjustierungs-/Actions-Präfix weicht von der eingefrorenen Forecast-Receipt ab",
                    )
                link = next(
                    (
                        r
                        for r in receipt["bar_links"]
                        if r["trade_date"] == forecast["target_session"]
                    ),
                    None,
                )
                if link is None:
                    raise ForecastError("outcome_not_available", "Abgeschlossener Zielkurs fehlt")
                evidence = {
                    "receipt_id": receipt["id"],
                    "target_revision_id": link["revision_id"],
                    "received_at": receipt["received_at"],
                    "available_at": receipt["available_at"],
                    "source_kind": receipt["source_kind"],
                    "forecast_saved_at": marker["saved_at"],
                }
                payload = record_outcome(
                    self.store,
                    forecast["id"],
                    prices,
                    source,
                    clock=self.clock,
                    persist=False,
                    evidence=evidence,
                )
                payload["prediction_correct"] = payload["actual"] == forecast["predicted_class"]
                payload["input_fingerprint"] = canonical_hash(
                    {
                        k: v
                        for k, v in payload.items()
                        if k not in {"input_fingerprint", "calculated_at"}
                    }
                )
                original = self.store.get("outcomes", forecast["id"])
                if original is None:
                    immutable_documents(self.store, [("outcomes", forecast["id"], payload)])
                    state = "recorded"
                elif (
                    original["target_close"] == payload["target_close"]
                    and original["feature_close"] == payload["feature_close"]
                ):
                    state = "unchanged"
                else:
                    # First accepted outcome remains immutable; later compatible labels are separate.
                    revision_id = "outcome-revision:" + canonical_hash(
                        [forecast["id"], payload["input_fingerprint"]]
                    )
                    if self.store.get("market_runs", revision_id) is None:
                        self.event(
                            revision_id,
                            {
                                "kind": "current_outcome_revision",
                                "forecast_id": forecast["id"],
                                "outcome": payload,
                            },
                        )
                    state = "revision_recorded"
                results.append({"forecast_id": forecast["id"], "status": state})
            except (ForecastError, MarketDataError) as error:
                conflict = {
                    "kind": "current_outcome_blocked",
                    "forecast_id": forecast["id"],
                    "code": error.code,
                    "at": stamp(self.clock()),
                }
                self.market.event(
                    "current_outcome_blocked", **{k: v for k, v in conflict.items() if k != "kind"}
                )
                results.append(
                    {"forecast_id": forecast["id"], "status": "blocked", "code": error.code}
                )
        return results

    def verify(self):
        """Explicit pre-activation inference check. Never writes forecasts or starts T0."""
        self.gate(verification=True)
        with self.engine.lease("current-pipeline"):
            decision, predictions = self.clock(), []
            for ticker in self.protocol["universe"]:
                documents, _ = self.paired_documents(ticker, decision, verification=True)
                predictions.extend(
                    {"id": identity, **payload}
                    for name, identity, payload in documents
                    if name == "forecasts"
                )
            identity = "current-validation:" + str(uuid4())
            payload = {
                "kind": "current_pipeline_validation",
                "protocol_hash": self.protocol_hash,
                "source_kind": "fixture" if self.fixture_mode else "provider",
                "validated_at": stamp(self.clock()),
                "rights_reference_sha256": checksum(self.settings.market_rights_reference),
                "declared_delay_seconds": self.settings.market_delay_seconds,
                "predictions": predictions,
            }
            payload["input_fingerprint"] = canonical_hash(payload)
            immutable_documents(self.store, [("backtests", identity, payload)])
            return {
                "validation_id": identity,
                "source_kind": payload["source_kind"],
                "predictions": len(predictions),
                "forecast_rows_created": 0,
            }

    def accept(self, validation_id, evidence_reference):
        self.gate(verification=True)
        validation = self.store.get("backtests", validation_id)
        if (
            self.fixture_mode
            or not validation
            or validation.get("source_kind") != "provider"
            or validation.get("kind") != "current_pipeline_validation"
            or validation.get("protocol_hash") != self.protocol_hash
            or validation.get("rights_reference_sha256")
            != checksum(self.settings.market_rights_reference)
            or validation.get("declared_delay_seconds") != self.settings.market_delay_seconds
            or utc(validation["validated_at"]) > utc(self.clock())
            or not evidence_reference.strip()
            or len(evidence_reference) > 240
        ):
            raise ForecastError(
                "acceptance_required",
                "Echte lokale Validierung und nicht geheime E2E-Nachweisreferenz erforderlich; Fixtures reichen nicht",
            )
        expected = {
            (t, m["artifact_id"])
            for t in self.protocol["universe"]
            for m in self.protocol["models"]
        }
        if {(p["ticker"], p["model_id"]) for p in validation["predictions"]} != expected or any(
            p["source_kind"] != "provider" for p in validation["predictions"]
        ):
            raise ForecastError(
                "acceptance_required",
                "Vollständige echte Fünf-Aktien-/Zwei-Modell-Validierung fehlt",
            )
        identity = "current-acceptance:" + canonical_hash(
            [validation_id, checksum(evidence_reference)]
        )
        if self.store.get("market_runs", identity):
            return {"acceptance_id": identity, "automatic_activation": False}
        self.event(
            identity,
            {
                "kind": "current_acceptance",
                "validation_id": validation_id,
                "protocol_hash": self.protocol_hash,
                "rights_reference_sha256": validation["rights_reference_sha256"],
                "declared_delay_seconds": validation["declared_delay_seconds"],
                "e2e_reference_sha256": checksum(evidence_reference),
                "accepted_at": stamp(self.clock()),
                "operator_attestation": True,
            },
        )
        return {"acceptance_id": identity, "automatic_activation": False}
