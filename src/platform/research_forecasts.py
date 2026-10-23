"""Explicit research jobs on frozen M4 artifacts and the existing document Store.

No training, market download, model promotion or automatic outcome processing.
"""

from contextlib import contextmanager
from datetime import timezone
from typing import Literal
from uuid import uuid4

import exchange_calendars as xcals
import pandas as pd
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .forecast_contract import (
    ForecastError,
    ResearchPrediction,
    checked_prices,
    prepare_snapshot,
    utc,
    utc_now,
)
from .model_artifacts import ID_PATTERN, ArtifactRepository, canonical_hash, file_hash
from .model_training import reference_inputs
from .store import TABLES, utcnow


class ForecastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    artifact_id: str = Field(pattern=ID_PATTERN)
    model_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    ticker: Literal["AAPL", "MSFT", "NVDA", "SAP.DE", "ALV.DE"]
    mode: Literal["historical_replay", "current"]
    decision_at: AwareDatetime
    horizon: Literal["next_session"] = "next_session"

    @field_validator("decision_at")
    @classmethod
    def normalize(cls, value):
        return value.astimezone(timezone.utc)

    def identity(self):
        # Mode/input versions deliberately excluded: altered inputs must conflict.
        return "rf-" + canonical_hash(
            {
                "artifact_id": self.artifact_id,
                "ticker": self.ticker,
                "decision_at": self.decision_at.isoformat(),
                "horizon": self.horizon,
            }
        )


def immutable_documents(store, documents):
    """INSERT first, then compare under the same SQLite/PostgreSQL transaction.

    Existing Store.add semantics stay intact for legacy callers. All documents
    in this transaction are rolled back when any semantic fingerprint conflicts.
    """
    result = {}
    with store.engine.begin() as conn:
        for name, identity, payload in documents:
            if name not in {"models", "forecasts", "outcomes", "backtests"}:
                raise ValueError("Nicht unterstütztes unveränderliches Forschungsdokument")
            store.add(name, payload, identity, connection=conn)
            row = (
                conn.execute(
                    select(TABLES[name]).where(
                        TABLES[name].c.id == f"{store.settings.mode}:{identity}"
                    )
                )
                .mappings()
                .one()
            )
            if row["payload"].get("input_fingerprint") != payload["input_fingerprint"]:
                raise ForecastError(
                    "input_conflict",
                    "Gespeicherte Forschungsanforderung hat abweichende Eingaben; Original bleibt unverändert",
                )
            result[name] = store._record(row)
    return result


class ResearchForecastEngine:
    def __init__(self, store, repository=None, clock=utc_now, inputs=None):
        self.store, self.clock = store, clock
        settings = store.settings
        self.repository = repository or ArtifactRepository(
            settings.research_artifact_dir or settings.runtime_dir / "research-models"
        )
        # Injection supports reproducible tests, never client-supplied paths/data.
        self.inputs = inputs

    def catalog(self):
        root = self.repository.root
        if not root.exists():
            return []
        try:
            ids = self.repository._registry()["artifacts"]
        except (OSError, ValueError):
            return []
        compatible = []
        for identity in ids:
            try:
                meta = self.repository.metadata(identity)
                compatible.append(
                    {
                        "artifact_id": identity,
                        "model_version": meta.model_version,
                        "name": meta.model_id,
                        "status": meta.status,
                        "forecast_enabled": False,
                        "created_at": meta.created_at.isoformat(),
                        "tickers": list(meta.instruments),
                        "training_spec": meta.training_spec,
                    }
                )
            except (OSError, ValueError):
                continue  # Incompatible/corrupt entries are never offered for selection.
        return compatible

    def prepare(self, request):
        if not self.store.settings.research_trust_local_artifacts:
            raise ForecastError(
                "trust_required",
                "Lokale Forschungsartefakte sind nicht freigegeben: SI_RESEARCH_TRUST_LOCAL_ARTIFACTS prüfen",
            )
        try:
            meta = self.repository.metadata(
                request.artifact_id, expected_version=request.model_version
            )
        except ForecastError:
            raise
        except (OSError, ValueError, KeyError, TypeError):
            raise ForecastError(
                "artifact_unavailable",
                "Lokale Modellmetadaten sind nicht lesbar; vertrauenswürdige Registry prüfen",
            ) from None
        if request.ticker not in meta.instruments:
            raise ForecastError("unknown_instrument", "Aktie gehört nicht zum Modellartefakt")
        if self.inputs:
            prices, instruments, source = self.inputs(request)
        else:
            prices, instruments, source = reference_inputs([request.ticker])
            if request.mode == "current" and self.store.settings.mode != "demo":
                # The legacy OHLCV table has no actual observation timestamps.
                # A new query timestamp must never masquerade as original availability.
                raise ForecastError(
                    "missing_provenance",
                    "Aktuelle Kursdaten benötigen belegte Beobachtungszeiten; die bestehende Kurstabelle liefert diese noch nicht",
                )
        if instruments[request.ticker] != meta.instruments[request.ticker]:
            raise ForecastError("instrument_version", "Instrumentzuordnung weicht vom Artefakt ab")
        try:
            snapshot = prepare_snapshot(
                prices,
                instruments[request.ticker],
                source,
                mode=request.mode,
                decision_at=request.decision_at,
                delay_seconds=meta.training_spec["publication_delay_seconds"],
                clock=self.clock,
            )
        except ForecastError:
            raise
        except ValueError:
            raise ForecastError(
                "invalid_snapshot",
                "Ungültiger Prognosezeitpunkt oder Snapshot: Börsenkalender, Datenbeobachtung und zeitliche Reihenfolge prüfen",
            ) from None
        fingerprint = canonical_hash(
            {
                "request": request.model_dump(mode="json"),
                "snapshot": snapshot.model_dump(mode="json", exclude={"prepared_at"}),
                "model_version": meta.model_version,
                "metadata_sha256": canonical_hash(meta.model_dump(mode="json")),
                "artifact_sha256": file_hash(
                    self.repository.path(request.artifact_id) / "model.joblib"
                ),
            }
        )
        return meta, snapshot, fingerprint

    def claim(self, identity):
        """Cross-process exclusion using the existing lease table, separate keyspace.

        No timeout-based takeover: a slow process must not overlap its successor.
        An unclean process exit requires explicit operator verification/recovery.
        """
        owner = str(uuid4())
        table = TABLES["news_locks"]
        statement = pg_insert if self.store.engine.dialect.name == "postgresql" else sqlite_insert
        with self.store.engine.begin() as conn:
            result = conn.execute(
                statement(table)
                .values(
                    id=f"{self.store.settings.mode}:research:{identity}",
                    mode=self.store.settings.mode,
                    created_at=utcnow(),
                    payload={"owner": owner, "purpose": "research_forecast"},
                )
                .on_conflict_do_nothing()
            )
        if result.rowcount != 1:
            raise ForecastError(
                "job_busy",
                "Diese Forschungsanforderung läuft bereits oder benötigt nach Abbruch eine geprüfte Lock-Freigabe",
            )
        return owner

    def release(self, identity, owner):
        table = TABLES["news_locks"]
        with self.store.engine.begin() as conn:
            conn.execute(
                delete(table).where(
                    table.c.id == f"{self.store.settings.mode}:research:{identity}",
                    table.c.payload["owner"].as_string() == owner,
                )
            )

    @contextmanager
    def lease(self, identity):
        owner = self.claim(identity)
        try:
            yield
        finally:
            self.release(identity, owner)

    def run(self, request):
        with self.lease(request.identity()):
            return self.run_prepared(request, self.prepare(request))

    def run_prepared(self, request, prepared):
        meta, snapshot, fingerprint = prepared
        identity = request.identity()
        existing = self.store.get("forecasts", identity)
        if existing:
            if existing.get("input_fingerprint") != fingerprint:
                raise ForecastError(
                    "input_conflict",
                    "Abweichende Eingaben für gespeicherte Prognose; Original bleibt unverändert",
                )
            return {"forecast_id": identity, "reused": True}
        loaded = self.repository.load(
            request.artifact_id, trusted=True, expected_version=request.model_version
        )
        expected = canonical_hash(
            {
                "request": request.model_dump(mode="json"),
                "snapshot": snapshot.model_dump(mode="json", exclude={"prepared_at"}),
                "model_version": loaded.metadata.model_version,
                "metadata_sha256": canonical_hash(loaded.metadata.model_dump(mode="json")),
                "artifact_sha256": loaded.checksum,
            }
        )
        if expected != fingerprint:
            raise ForecastError(
                "artifact_changed", "Modellartefakt hat sich seit Auftragserstellung verändert"
            )
        prediction = loaded.predict_research(snapshot, clock=self.clock)
        payload = prediction.model_dump(mode="json") | {
            "kind": "research_forecast",
            "input_fingerprint": fingerprint,
            "forecast_at": prediction.generated_at.isoformat(),
            "model_name": meta.model_id,
            "predicted_class": int(prediction.probability >= 0.5),
        }
        model = {
            "kind": "final_research",
            "name": meta.model_id,
            "status": "research_only",
            "forecast_enabled": False,
            "calibrated": True,
            "metrics": {
                "train_start": meta.training_period["start"],
                "train_end": meta.training_period["end"],
            },
            "calibration_period": meta.calibration_period,
            "model_version": meta.model_version,
            "artifact_sha256": prediction.artifact_sha256,
            "input_fingerprint": canonical_hash(meta.model_dump(mode="json")),
            "warning": "Eingefrorenes Forschungsartefakt; keine operative Freigabe",
        }
        saved = immutable_documents(
            self.store,
            [
                ("models", request.artifact_id, model),
                ("forecasts", identity, payload),
            ],
        )
        return {"forecast_id": saved["forecasts"]["id"], "reused": False}


def record_outcome(store, forecast_id, prices, source, *, clock=utc_now):
    """Explicit validated preparation only; no API trigger, scheduler or fake future result."""
    original = store.get("forecasts", forecast_id)
    if not original or original.get("kind") != "research_forecast":
        raise ForecastError("unknown_forecast", "Forschungsprognose nicht gefunden")
    fields = {name: original[name] for name in ResearchPrediction.model_fields}
    forecast = ResearchPrediction.model_validate(fields)
    now = utc(clock())
    cal = xcals.get_calendar(forecast.calendar)
    end = cal.session_close(pd.Timestamp(forecast.target_session)) + pd.Timedelta(
        seconds=forecast.publication_delay_seconds
    )
    if now < end or utc(source.observed_at) < end or utc(source.observed_at) > now:
        raise ForecastError(
            "outcome_not_available",
            "Zielsitzung oder tatsächliche Kursbeobachtung noch nicht verfügbar",
        )
    instrument = {"calendar": forecast.calendar}
    frame = checked_prices(prices, {forecast.ticker: instrument}, end=forecast.target_session)
    if set(frame.ticker) != {forecast.ticker}:
        raise ForecastError("outcome_prices", "Outcome benötigt genau das Prognoseinstrument")
    bars = frame.set_index("trade_date")
    dates = [pd.Timestamp(forecast.feature_as_of), pd.Timestamp(forecast.target_session)]
    if not all(day in bars.index for day in dates):
        raise ForecastError("outcome_prices", "Feature- und Zielschlusskurs fehlen")
    from .market import digest

    if digest(frame[frame.trade_date <= dates[0]].reset_index(drop=True)) != forecast.data_version:
        raise ForecastError(
            "outcome_revision", "Kursverlauf weicht vom gespeicherten Forecast-Datenstand ab"
        )
    close, target = [float(bars.loc[day, "close_price"]) for day in dates]
    payload = {
        "forecast_id": forecast_id,
        "kind": "research_outcome",
        "actual": int(target > close),
        "feature_close": close,
        "target_close": target,
        "target_session": str(forecast.target_session),
        "outcome_at": end.isoformat(),
        "observed_at": source.observed_at.isoformat(),
        "calculated_at": now.isoformat(),
        "source": source.model_dump(mode="json"),
    }
    payload["input_fingerprint"] = canonical_hash(
        {k: v for k, v in payload.items() if k != "calculated_at"}
    )
    return immutable_documents(store, [("outcomes", forecast_id, payload)])["outcomes"]
