from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

try:
    from .config import (
        RAW_PRICE_DIR,
        RAW_PROFILE_DIR,
        TICKERS,
        YFINANCE_CACHE_DIR,
        ticker_file_stem,
    )
except ImportError:  # Allows: python src/ingestion.py
    from config import (
        RAW_PRICE_DIR,
        RAW_PROFILE_DIR,
        TICKERS,
        YFINANCE_CACHE_DIR,
        ticker_file_stem,
    )


def prepare_directories() -> None:
    """Create the raw-layer directories."""

    RAW_PRICE_DIR.mkdir(parents=True, exist_ok=True)
    RAW_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    YFINANCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    yf.set_tz_cache_location(str(YFINANCE_CACHE_DIR))


def save_raw_data(
    ticker_symbol: str,
    info: dict,
    history: pd.DataFrame,
    run_timestamp: str,
) -> tuple[Path, Path]:
    """Persist one immutable API snapshot as CSV and JSON."""

    safe_ticker = ticker_file_stem(ticker_symbol)
    price_file = RAW_PRICE_DIR / f"{safe_ticker}_{run_timestamp}.csv"
    profile_file = RAW_PROFILE_DIR / f"{safe_ticker}_{run_timestamp}.json"

    history.to_csv(price_file)
    profile_file.write_text(
        json.dumps(info, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    return price_file, profile_file


def fetch_daily_history(ticker, **options) -> pd.DataFrame:
    """Shared daily-data request; callers own rights, timing, persistence and retries."""
    return ticker.history(interval="1d", auto_adjust=True, actions=True, **options)


def download_ticker(
    ticker_symbol: str,
    period: str = "5y",
    run_timestamp: str | None = None,
) -> tuple[Path, Path]:
    """Download and persist one ticker without writing to the curated database."""

    timestamp = run_timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    logging.info("Downloading raw data for %s", ticker_symbol)

    ticker = yf.Ticker(ticker_symbol)
    history = fetch_daily_history(ticker, period=period)

    if history.empty:
        raise ValueError(f"No historical price data received for {ticker_symbol}.")

    try:
        info = ticker.info or {}
    except Exception as error:  # Price data is still useful if profile lookup fails.
        logging.warning("Profile download failed for %s: %s", ticker_symbol, error)
        info = {}

    paths = save_raw_data(ticker_symbol, info, history, timestamp)
    logging.info("%s: saved %s raw price rows", ticker_symbol, len(history))
    return paths


def run_ingestion(
    tickers: tuple[str, ...] | list[str] = TICKERS,
    period: str = "5y",
) -> dict[str, str]:
    """Download all requested tickers and return a per-ticker result."""

    prepare_directories()
    run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results: dict[str, str] = {}

    for ticker_symbol in tickers:
        try:
            download_ticker(ticker_symbol, period, run_timestamp)
            results[ticker_symbol] = "ok"
        except Exception as error:
            logging.exception("Ingestion failed for %s", ticker_symbol)
            results[ticker_symbol] = f"failed: {error}"
        time.sleep(1)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Download Yahoo Finance raw data")
    parser.add_argument("--tickers", nargs="+", default=list(TICKERS))
    parser.add_argument("--period", default="5y")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    results = run_ingestion(args.tickers, args.period)

    for ticker_symbol, result in results.items():
        print(f"{ticker_symbol}: {result}")

    if any(result != "ok" for result in results.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
