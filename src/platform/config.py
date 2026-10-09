from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.config import PROJECT_ROOT


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SI_", env_file=PROJECT_ROOT / ".env", extra="ignore"
    )
    mode: Literal["demo", "live"] = "demo"
    runtime_dir: Path = PROJECT_ROOT / ".runtime"
    alpha_vantage_key: str = ""
    finbert_enabled: bool = False
    finbert_device: int = -1
    allowed_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]
    mutation_token: str = ""
    allowed_hosts: list[str] = ["127.0.0.1", "localhost", "testserver"]
    api_docs_enabled: bool = True
    allow_mutations: bool = True
    proxy_token: str = ""
    required_schema_version: int = 1
    news_enabled: bool = False
    news_provider: Literal["finnhub", "alpha_vantage", "rss"] = "finnhub"
    finnhub_key: str = ""
    news_rights_accepted: bool = False
    news_store_summaries: bool = False
    news_rss_feeds: list[dict] = Field(default_factory=list, max_length=10)
    news_auto_refresh: bool = False
    news_interval_seconds: int = Field(default=900, ge=300, le=86400)
    news_max_cycles: int = Field(default=24, ge=1, le=288)
    news_daily_budget: int = Field(default=100, ge=1, le=1000)
    news_batch_size: int = Field(default=8, ge=1, le=32)
    news_stale_hours: int = Field(default=24, ge=1, le=168)

    @field_validator("news_rss_feeds")
    @classmethod
    def validate_feed_config(cls, feeds):
        for feed in feeds:
            if not isinstance(feed.get("url"), str) or not isinstance(feed.get("name"), str):
                raise ValueError("RSS-Konfiguration benötigt url und name als Text")
            if feed.get("ticker") is not None and not isinstance(feed["ticker"], str):
                raise ValueError("RSS ticker muss ein Text sein")
            if feed.get("rights_confirmed") not in (True, False, None) or isinstance(
                feed.get("rights_confirmed"), str
            ):
                raise ValueError("RSS rights_confirmed muss ein JSON-Boolean sein")
        return feeds


class Instrument(BaseModel):
    ticker: str = Field(pattern=r"^[A-Z0-9][A-Z0-9.\-^]{0,19}$")
    company: str = Field(min_length=1, max_length=120)
    exchange: str = Field(min_length=1, max_length=40)
    country: str = Field(min_length=2, max_length=40)
    region: Literal["USA", "Europa"]
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    timezone: str
    calendar: str = "XNYS"
    sector: str = Field(default="Unbekannt", max_length=80)
    yahoo_symbol: str = Field(pattern=r"^[A-Z0-9][A-Z0-9.\-^]{0,19}$")
    news_symbol: str | None = Field(default=None, pattern=r"^[A-Z0-9][A-Z0-9.\-]{0,19}$")

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError("Unbekannte Börsenzeitzone") from None
        return value

    @field_validator("calendar")
    @classmethod
    def valid_calendar(cls, value):
        if value not in {"XNYS", "XNAS", "XETR", "XLON", "XPAR"}:
            raise ValueError("Nicht unterstützter Börsenkalender")
        return value


DEFAULT_INSTRUMENTS = [
    Instrument(
        ticker=t,
        company=n,
        exchange=e,
        country=c,
        region=r,
        currency=u,
        timezone=z,
        calendar=k,
        sector=s,
        yahoo_symbol=t,
        news_symbol=a,
    )
    for t, n, e, c, r, u, z, k, s, a in [
        (
            "AAPL",
            "Apple",
            "NASDAQ",
            "US",
            "USA",
            "USD",
            "America/New_York",
            "XNYS",
            "Technologie",
            "AAPL",
        ),
        (
            "MSFT",
            "Microsoft",
            "NASDAQ",
            "US",
            "USA",
            "USD",
            "America/New_York",
            "XNYS",
            "Technologie",
            "MSFT",
        ),
        (
            "NVDA",
            "NVIDIA",
            "NASDAQ",
            "US",
            "USA",
            "USD",
            "America/New_York",
            "XNYS",
            "Technologie",
            "NVDA",
        ),
        (
            "SAP.DE",
            "SAP",
            "XETRA",
            "DE",
            "Europa",
            "EUR",
            "Europe/Berlin",
            "XETR",
            "Technologie",
            None,
        ),
        (
            "ALV.DE",
            "Allianz",
            "XETRA",
            "DE",
            "Europa",
            "EUR",
            "Europe/Berlin",
            "XETR",
            "Versicherung",
            None,
        ),
    ]
]
