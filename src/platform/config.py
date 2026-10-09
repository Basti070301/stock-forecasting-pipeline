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
