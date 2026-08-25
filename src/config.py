from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = PROJECT_ROOT / "data"
RAW_PRICE_DIR = DATA_DIR / "raw" / "prices"
RAW_PROFILE_DIR = DATA_DIR / "raw" / "profiles"
PROCESSED_PRICE_DIR = DATA_DIR / "processed" / "prices"
FEATURE_DIR = DATA_DIR / "features"
REPORT_DIR = PROJECT_ROOT / "reports"
MODEL_DIR = PROJECT_ROOT / "models"
YFINANCE_CACHE_DIR = PROJECT_ROOT / ".cache" / "yfinance"

TICKERS = (
    "AAPL",
    "MSFT",
    "NVDA",
    "SAP.DE",
    "ALV.DE",
)


def ticker_file_stem(ticker_symbol: str) -> str:
    """Return a filesystem-safe representation of a ticker symbol."""

    return ticker_symbol.replace(".", "_")
