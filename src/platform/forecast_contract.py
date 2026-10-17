"""M4.0: calendar-aware research contract. No publication, market fetch or order execution."""

from datetime import date, datetime, timedelta, timezone
from typing import Literal

import exchange_calendars as xcals
import numpy as np
import pandas as pd
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from src.feature_engineering import FEATURE_COLUMNS, calculate_features

from .market import digest

CONTRACT_VERSION = "next-session-close-direction-v1"
FEATURE_VERSION = "pipeline-six-v1"
INPUT_COLUMNS = [*FEATURE_COLUMNS, "ticker"]
FEATURE_SCHEMA = {**dict.fromkeys(FEATURE_COLUMNS, "finite_float"), "ticker": "string"}


class ForecastError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def utc_now():
    return datetime.now(timezone.utc)


def utc(value):
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None or pd.isna(stamp):
        raise ForecastError(
            "timezone_required", "Ein eindeutiger Zeitpunkt mit Zeitzone ist erforderlich"
        )
    return stamp.tz_convert("UTC")


class SourceProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["historical_snapshot", "stored_market_data"]
    observed_at: AwareDatetime
    snapshot_hashes: dict[str, str] = Field(default_factory=dict)

    @field_validator("observed_at")
    @classmethod
    def observed_utc(cls, value):
        return value.astimezone(timezone.utc)

    @field_validator("snapshot_hashes")
    @classmethod
    def valid_hashes(cls, value):
        import re

        if any(not re.fullmatch(r"[a-f0-9]{64}", checksum) for checksum in value.values()):
            raise ValueError("Ungültiger SHA256-Datenquellenhash")
        return value


class FeatureSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    ticker: str
    exchange: str
    calendar: str
    feature_as_of: date
    data_available_at: AwareDatetime
    decision_at: AwareDatetime
    prepared_at: AwareDatetime
    target_session: date
    mode: Literal["current", "historical_replay"]
    data_status: Literal["current", "historical_replay"]
    contract_version: Literal["next-session-close-direction-v1"] = CONTRACT_VERSION
    feature_version: Literal["pipeline-six-v1"] = FEATURE_VERSION
    publication_delay_seconds: int = Field(ge=0, le=86400)
    data_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    source: SourceProvenance
    features: dict[str, float]

    @field_validator("features", mode="before")
    @classmethod
    def strict_features(cls, value):
        validate_feature_values(value)
        return value

    @model_validator(mode="after")
    def temporal_and_feature_contract(self):
        validate_feature_values(self.features)
        if self.mode != self.data_status:
            raise ForecastError("mode_mismatch", "Datenstatus und Replay-Modus widersprechen sich")
        cal = xcals.get_calendar(self.calendar)
        day = pd.Timestamp(self.feature_as_of)
        if not cal.is_session(day) or cal.next_session(day).date() != self.target_session:
            raise ForecastError(
                "target_session", "Ziel ist nicht die nächste gültige Handelssitzung"
            )
        earliest = cal.session_close(day) + pd.Timedelta(seconds=self.publication_delay_seconds)
        if utc(self.data_available_at) < max(earliest, utc(self.source.observed_at)):
            raise ForecastError("availability", "Datenverfügbarkeit liegt vor Schluss/Abrufzeit")
        if not utc(self.data_available_at) <= utc(self.decision_at) <= utc(self.prepared_at):
            raise ForecastError(
                "availability", "Daten oder Entscheidungszeitpunkt liegen in der Zukunft"
            )
        if (
            latest_available_session(
                self.calendar, self.decision_at, self.publication_delay_seconds
            )
            != day
        ):
            raise ForecastError(
                "stale_data", "Feature-Stichtag ist für diesen Entscheidungszeitpunkt veraltet"
            )
        if self.mode == "current":
            if self.source.kind == "historical_snapshot":
                raise ForecastError(
                    "historical_source",
                    "Historischer Snapshot benötigt ausdrücklichen Replay-Modus",
                )
            if utc(self.prepared_at) - utc(self.decision_at) > pd.Timedelta(minutes=5):
                raise ForecastError(
                    "backdated_current", "Rückdatierte aktuelle Prognose ist nicht zulässig"
                )
        return self


class ResearchPrediction(FeatureSnapshot):
    """An isolated test result; deliberately no automatic Store/API writer."""

    model_id: str
    model_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_created_at: AwareDatetime
    model_knowledge_available_at: AwareDatetime
    generated_at: AwareDatetime
    horizon: Literal["next_session"] = "next_session"
    target_definition: Literal["Close(t+1) > Close(t)"] = "Close(t+1) > Close(t)"
    probability: float = Field(ge=0, le=1, allow_inf_nan=False)
    status: Literal["research_only"] = "research_only"
    forecast_enabled: Literal[False] = False
    counterfactual_model_replay: bool

    @model_validator(mode="after")
    def prediction_timing(self):
        if utc(self.generated_at) < max(utc(self.prepared_at), utc(self.model_created_at)):
            raise ForecastError("prediction_time", "Ergebnis liegt vor Modell-/Eingabeerstellung")
        if utc(self.model_knowledge_available_at) > utc(self.decision_at):
            raise ForecastError(
                "model_not_available", "Modellwissen liegt nach dem Entscheidungszeitpunkt"
            )
        counterfactual = utc(self.model_created_at) > utc(self.decision_at)
        if counterfactual != self.counterfactual_model_replay or (
            counterfactual and self.mode != "historical_replay"
        ):
            raise ForecastError(
                "replay_required",
                "Später erzeugtes Modell muss als kontrafaktischer Replay markiert sein",
            )
        return self


def latest_available_session(calendar, decision_at, delay_seconds=900):
    reference = utc(decision_at)
    cal = xcals.get_calendar(calendar)
    local_day = reference.tz_convert(cal.tz).tz_localize(None).normalize()
    day = cal.date_to_session(local_day, direction="previous")
    while cal.session_close(day) + pd.Timedelta(seconds=delay_seconds) > reference:
        day = cal.previous_session(day)
    return day.tz_localize(None)


def validate_feature_values(features):
    if set(features) != set(FEATURE_COLUMNS):
        raise ForecastError(
            "feature_schema", "Technische Features fehlen oder sind nicht kompatibel"
        )
    try:
        valid = all(
            not isinstance(value, (str, bool)) and np.isfinite(float(value))
            for value in features.values()
        )
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ForecastError(
            "incomplete_features", "Technische Features sind unvollständig oder nicht endlich"
        )


def checked_prices(prices, instruments, *, end=None):
    """Check normalized existing pipeline output; never silently fill a missing trading bar."""
    columns = [
        "ticker",
        "trade_date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
    ]
    if prices.empty or not set(columns).issubset(prices.columns):
        raise ForecastError("missing_prices", "Vollständige OHLCV-Kursdaten fehlen")
    frame = prices.loc[:, columns].copy()
    try:
        frame["trade_date"] = pd.to_datetime(frame.trade_date, errors="raise")
        if (
            frame.trade_date.dt.tz is not None
            or frame.trade_date.isna().any()
            or not frame.trade_date.eq(frame.trade_date.dt.normalize()).all()
        ):
            raise ValueError("Handelstage müssen lokale Kalenderdaten sein")
        if end is not None:
            frame = frame[frame.trade_date <= pd.Timestamp(end)].copy()
        frame[columns[2:]] = frame[columns[2:]].apply(pd.to_numeric, errors="raise")
    except (ValueError, TypeError, AttributeError):
        raise ForecastError(
            "invalid_prices", "Kursdaten enthalten ungültige Datums-/Zahlenwerte"
        ) from None
    if frame.empty:
        raise ForecastError("missing_prices", "Keine verfügbaren Kursdaten vor dem Stichtag")
    values = frame[columns[2:]]
    if (
        frame.ticker.isna().any()
        or frame.duplicated(["ticker", "trade_date"]).any()
        or not np.isfinite(values.to_numpy(dtype=float, na_value=np.nan)).all()
        or not values[columns[2:6]].gt(0).all().all()
        or not values.volume.ge(0).all()
    ):
        raise ForecastError("invalid_prices", "Doppelte, fehlende oder ungültige OHLCV-Werte")
    if not (
        values.high_price.ge(values[["open_price", "close_price", "low_price"]].max(axis=1))
        & values.low_price.le(values[["open_price", "close_price", "high_price"]].min(axis=1))
    ).all():
        raise ForecastError("invalid_prices", "OHLC-Preise widersprechen sich")
    for ticker, group in frame.groupby("ticker"):
        if ticker not in instruments:
            raise ForecastError(
                "unknown_instrument", "Instrument benötigt bestätigte Börsen-/Kalenderzuordnung"
            )
        days = pd.DatetimeIndex(group.trade_date.sort_values())
        cal = xcals.get_calendar(instruments[ticker]["calendar"])
        expected = cal.sessions_in_range(days.min(), days.max()).tz_localize(None)
        if not days.equals(expected):
            raise ForecastError(
                "missing_sessions", f"{ticker}: fehlende oder ungültige Handelssitzungen"
            )
    return frame.sort_values(["ticker", "trade_date"]).reset_index(drop=True)


def prepare_snapshot(
    prices,
    instrument,
    source,
    *,
    mode="current",
    decision_at=None,
    delay_seconds=900,
    clock=utc_now,
):
    prepared_at = utc(clock())
    reference = utc(decision_at) if decision_at is not None else prepared_at
    if mode not in {"current", "historical_replay"} or not 0 <= delay_seconds <= 86400:
        raise ForecastError("invalid_mode", "Replay-Modus oder Datenverzögerung ist ungültig")
    expected = latest_available_session(instrument["calendar"], reference, delay_seconds)
    selected = prices[prices.ticker == instrument["ticker"]] if "ticker" in prices else prices
    frame = checked_prices(selected, {instrument["ticker"]: instrument}, end=expected)
    latest = frame.trade_date.max()
    if latest != expected:
        raise ForecastError(
            "stale_data",
            f"Veraltete Kurse: {latest.date()}, erwartet {expected.date()} ({instrument['calendar']})",
        )
    features = calculate_features(frame).iloc[-1]
    values = {name: float(features[name]) for name in FEATURE_COLUMNS}
    validate_feature_values(values)
    cal = xcals.get_calendar(instrument["calendar"])
    available = max(
        cal.session_close(expected) + timedelta(seconds=delay_seconds), utc(source.observed_at)
    )
    return FeatureSnapshot(
        ticker=instrument["ticker"],
        exchange=instrument["exchange"],
        calendar=instrument["calendar"],
        feature_as_of=latest.date(),
        data_available_at=available.to_pydatetime(),
        decision_at=reference.to_pydatetime(),
        prepared_at=prepared_at.to_pydatetime(),
        target_session=cal.next_session(expected).date(),
        mode=mode,
        data_status=mode,
        publication_delay_seconds=delay_seconds,
        data_version=digest(frame),
        source=source,
        features=values,
    )
