"""Bounded daily adapter; no profile requests, file writes, scheduler or model calls."""

import hashlib
import json
from datetime import date, timedelta, timezone
from importlib.metadata import version
from typing import Literal, Protocol
from uuid import UUID, uuid4

import numpy as np
import pandas as pd
import yfinance as yf
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from yfinance.exceptions import YFRateLimitError

from src.ingestion import fetch_daily_history

from .config import DEFAULT_INSTRUMENTS
from .forecast_contract import utc_now

INSTRUMENTS = {i.ticker: i.model_dump() for i in DEFAULT_INSTRUMENTS}
SOURCE_COLUMNS = ["Open", "High", "Low", "Close", "Volume", "Dividends", "Stock Splits"]


def stamp(value):
    parsed = pd.Timestamp(value)
    if pd.isna(parsed) or parsed.tzinfo is None:
        raise MarketDataError("timezone", "Eindeutiger UTC-/Zeitzonen-Zeitpunkt erforderlich")
    return parsed.tz_convert("UTC").to_pydatetime().isoformat(timespec="microseconds")


def checksum(payload):
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


class MarketDataError(ValueError):
    def __init__(self, code, message, *, retryable=False, cooldown=60):
        super().__init__(message)
        self.code, self.retryable, self.cooldown = code, retryable, cooldown


class DailyProvider(Protocol):
    """History adapters must return receipts, not unversioned price arrays."""

    name: str

    def configured_reason(self) -> str | None: ...

    def fetch(self, ticker: str, start: date, end: date) -> "MarketReceipt": ...


class MarketReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    receipt_id: UUID = Field(default_factory=uuid4)
    ticker: Literal["AAPL", "MSFT", "NVDA", "SAP.DE", "ALV.DE"]
    provider: Literal["yfinance"] = "yfinance"
    source_kind: Literal["provider", "fixture"] = "provider"
    requested_start: date
    requested_end: date
    request_started_at: AwareDatetime
    received_at: AwareDatetime
    provider_published_at: AwareDatetime | None = None
    declared_delay_seconds: int | None = Field(default=None, ge=0, le=86400)
    payload: str = Field(max_length=4 * 1024 * 1024)
    adapter_version: Literal["yfinance-daily-v1"] = "yfinance-daily-v1"
    library_version: str = Field(max_length=60)
    adjustment: Literal["yfinance_auto_adjust_true_actions_true_repair_false"] = (
        "yfinance_auto_adjust_true_actions_true_repair_false"
    )

    @field_validator("request_started_at", "received_at", "provider_published_at")
    @classmethod
    def normalize_time(cls, value):
        return value.astimezone(timezone.utc) if value else None

    @model_validator(mode="after")
    def ordered(self):
        if (
            self.requested_end < self.requested_start
            or (self.requested_end - self.requested_start).days > 732
        ):
            raise ValueError("Tagesdatenbereich muss geordnet und höchstens 733 Tage lang sein")
        if self.received_at < self.request_started_at:
            raise ValueError("Empfangszeit liegt vor Request-Start")
        if len(self.payload.encode("utf-8")) > 4 * 1024 * 1024:
            raise ValueError("Normalisierter Adapter-Payload überschreitet 4 MiB")
        return self

    @property
    def payload_sha256(self):
        return checksum(self.payload)


def encode_frame(frame):
    """Hash exactly this returned DataFrame projection, NOT unavailable HTTP wire bytes.

    Keep raw exchange offsets and invalid numeric values as null for quality auditing.
    clean_price_frame must not silently erase invalid source rows before this capture.
    """
    if not isinstance(frame.index, pd.DatetimeIndex) or len(frame) > 1000:
        raise MarketDataError("response_shape", "Ungültiger/zu großer Tagesdaten-DataFrame")
    columns = [name for name in SOURCE_COLUMNS if name in frame.columns]
    rows = []
    for index, row in frame.iterrows():
        values = {"Date": index.isoformat() if not pd.isna(index) else None}
        for name in columns:
            value = row[name]
            if value is None or pd.isna(value):
                value = None
            elif isinstance(value, (int, float, np.number)) and not isinstance(value, bool):
                value = float(value) if np.isfinite(value) else None
            else:
                value = str(value)[:100]
            values[name] = value
        rows.append(values)
    return canonical(
        {"format": "yfinance_dataframe_projection_v1", "columns": columns, "rows": rows}
    )


class YahooDailyProvider:
    name = "yfinance"

    def __init__(self, settings, ticker_factory=None, clock=utc_now):
        self.settings, self.clock = settings, clock
        self.ticker_factory = ticker_factory or yf.Ticker

    def configured_reason(self):
        if not self.settings.market_enabled:
            return "Tageskursabruf deaktiviert (SI_MARKET_ENABLED)"
        if (
            not self.settings.market_rights_accepted
            or not self.settings.market_rights_reference.strip()
        ):
            return "Erlaubter Providerzugang und dessen lokale Nachweisreferenz fehlen; kein echter Abruf"
        return None

    def fetch(self, ticker, start, end):
        reason = self.configured_reason()
        if reason:
            raise MarketDataError("access_blocked", reason)
        if ticker not in INSTRUMENTS or not start <= end or (end - start).days > 732:
            raise MarketDataError("request", "Nicht unterstützter Ticker oder Datumsbereich")
        started = self.clock()
        local_today = pd.Timestamp(started).tz_convert(INSTRUMENTS[ticker]["timezone"]).date()
        if end > local_today:
            raise MarketDataError("request", "Keine zukünftigen Tageskurse anfordern")
        try:
            # start inclusive, end exclusive in yfinance; never request company profiles.
            frame = fetch_daily_history(
                self.ticker_factory(ticker),
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                timeout=self.settings.market_timeout_seconds,
                keepna=True,
                repair=False,
                prepost=False,
                raise_errors=True,
            )
            received = self.clock()
        except YFRateLimitError:
            raise MarketDataError(
                "rate_limit", "Yahoo meldet Rate Limit; Abruf pausiert", cooldown=300
            ) from None
        except (TimeoutError, ConnectionError):
            raise MarketDataError(
                "transport", "Tageskursprovider: Timeout/Netzwerkfehler", retryable=True
            ) from None
        except Exception as error:
            # yfinance wraps several HTTP implementations; never serialize URL/crumbs.
            name = type(error).__name__.lower()
            retry = any(
                token in name for token in ("timeout", "connection", "request", "httperror")
            )
            raise MarketDataError(
                "transport" if retry else "provider",
                "Tageskursprovider nicht verfügbar; Zugang/Logs ohne Zugangsdaten prüfen",
                retryable=retry,
            ) from None
        return MarketReceipt(
            ticker=ticker,
            requested_start=start,
            requested_end=end,
            request_started_at=started,
            received_at=received,
            declared_delay_seconds=self.settings.market_delay_seconds,
            # No truthful HTTP status or publication timestamp is exposed by history().
            provider_published_at=None,
            library_version=version("yfinance"),
            payload=encode_frame(frame),
        )
