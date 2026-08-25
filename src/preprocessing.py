from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

try:
    from .config import (
        PROCESSED_PRICE_DIR,
        RAW_PRICE_DIR,
        RAW_PROFILE_DIR,
        TICKERS,
        ticker_file_stem,
    )
    from .database import get_engine
except ImportError:  # Allows: python src/preprocessing.py
    from config import (
        PROCESSED_PRICE_DIR,
        RAW_PRICE_DIR,
        RAW_PROFILE_DIR,
        TICKERS,
        ticker_file_stem,
    )
    from database import get_engine


UPSERT_STOCK_SQL = text(
    """
    INSERT INTO dim_stock (
        ticker, company_name, sector, industry, country,
        currency, exchange, market_cap
    )
    VALUES (
        :ticker, :company_name, :sector, :industry, :country,
        :currency, :exchange, :market_cap
    )
    ON CONFLICT (ticker)
    DO UPDATE SET
        company_name = EXCLUDED.company_name,
        sector = EXCLUDED.sector,
        industry = EXCLUDED.industry,
        country = EXCLUDED.country,
        currency = EXCLUDED.currency,
        exchange = EXCLUDED.exchange,
        market_cap = EXCLUDED.market_cap
    RETURNING stock_id;
    """
)

UPSERT_PRICE_SQL = text(
    """
    INSERT INTO fact_stock_price (
        stock_id, trade_date, open_price, high_price, low_price,
        close_price, volume, dividends, stock_splits
    )
    VALUES (
        :stock_id, :trade_date, :open_price, :high_price, :low_price,
        :close_price, :volume, :dividends, :stock_splits
    )
    ON CONFLICT (stock_id, trade_date)
    DO UPDATE SET
        open_price = EXCLUDED.open_price,
        high_price = EXCLUDED.high_price,
        low_price = EXCLUDED.low_price,
        close_price = EXCLUDED.close_price,
        volume = EXCLUDED.volume,
        dividends = EXCLUDED.dividends,
        stock_splits = EXCLUDED.stock_splits;
    """
)


def create_directories() -> None:
    PROCESSED_PRICE_DIR.mkdir(parents=True, exist_ok=True)


def find_latest_raw_file(directory: Path, ticker_symbol: str, suffix: str) -> Path:
    """Find the newest timestamped snapshot, with legacy filenames supported."""

    file_stem = ticker_file_stem(ticker_symbol)
    candidates = list(directory.glob(f"{file_stem}_*.{suffix}"))
    legacy_file = directory / f"{file_stem}.{suffix}"
    if legacy_file.exists():
        candidates.append(legacy_file)

    if not candidates:
        raise FileNotFoundError(
            f"No raw {suffix} file found for {ticker_symbol} in {directory}."
        )

    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name))


def load_profile(ticker_symbol: str) -> dict:
    """Load the newest company profile in current or legacy JSON shape."""

    profile_file = find_latest_raw_file(RAW_PROFILE_DIR, ticker_symbol, "json")
    payload = json.loads(profile_file.read_text(encoding="utf-8"))

    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    if isinstance(payload, dict):
        return payload
    raise ValueError(f"Unexpected profile structure in {profile_file}.")


def clean_price_frame(prices: pd.DataFrame, ticker_symbol: str) -> pd.DataFrame:
    """Normalize and validate a raw Yahoo Finance price frame."""

    frame = prices.copy()
    date_column = next(
        (column for column in ("Date", "Datetime") if column in frame.columns),
        None,
    )
    if date_column is None:
        raise ValueError("Raw price data must contain a Date or Datetime column.")

    required_source_columns = ("Open", "High", "Low", "Close", "Volume")
    missing_columns = [
        column for column in required_source_columns if column not in frame.columns
    ]
    if missing_columns:
        raise ValueError("Missing raw price columns: " + ", ".join(missing_columns))

    for optional_column in ("Dividends", "Stock Splits"):
        if optional_column not in frame.columns:
            frame[optional_column] = 0.0

    # Trading dates are exchange-local calendar dates. UTC conversion would
    # incorrectly move German midnight timestamps to the previous date.
    date_text = frame[date_column].astype("string").str.extract(
        r"^(\d{4}-\d{2}-\d{2})", expand=False
    )
    frame["trade_date"] = pd.to_datetime(
        date_text, format="%Y-%m-%d", errors="coerce"
    ).dt.date

    frame = frame.rename(
        columns={
            "Open": "open_price",
            "High": "high_price",
            "Low": "low_price",
            "Close": "close_price",
            "Volume": "volume",
            "Dividends": "dividends",
            "Stock Splits": "stock_splits",
        }
    )
    frame["ticker"] = ticker_symbol

    output_columns = [
        "ticker",
        "trade_date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "dividends",
        "stock_splits",
    ]
    numeric_columns = output_columns[2:]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = frame[output_columns].dropna(
        subset=["trade_date", "open_price", "high_price", "low_price", "close_price"]
    )
    frame = frame.drop_duplicates(subset=["ticker", "trade_date"], keep="last")

    price_columns = ["open_price", "high_price", "low_price", "close_price"]
    positive_prices = frame[price_columns].gt(0).all(axis=1)
    consistent_ohlc = (
        frame["high_price"].ge(frame[price_columns].max(axis=1))
        & frame["low_price"].le(frame[price_columns].min(axis=1))
    )
    valid_volume = frame["volume"].isna() | frame["volume"].ge(0)
    frame = frame.loc[positive_prices & consistent_ohlc & valid_volume].copy()

    frame["volume"] = frame["volume"].round().astype("Int64")
    frame["dividends"] = frame["dividends"].fillna(0.0)
    frame["stock_splits"] = frame["stock_splits"].fillna(0.0)

    return frame.sort_values(["ticker", "trade_date"]).reset_index(drop=True)


def clean_price_data(ticker_symbol: str) -> pd.DataFrame:
    raw_price_file = find_latest_raw_file(RAW_PRICE_DIR, ticker_symbol, "csv")
    return clean_price_frame(pd.read_csv(raw_price_file), ticker_symbol)


def save_processed_prices(ticker_symbol: str, prices: pd.DataFrame) -> Path:
    create_directories()
    processed_file = (
        PROCESSED_PRICE_DIR / f"{ticker_file_stem(ticker_symbol)}_clean.csv"
    )
    prices.to_csv(processed_file, index=False)
    return processed_file


def to_int_or_none(value) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)


def get_stock_id(
    connection: Connection,
    ticker_symbol: str,
    profile: dict,
) -> int:
    payload = {
        "ticker": ticker_symbol,
        "company_name": profile.get("longName") or profile.get("shortName"),
        "sector": profile.get("sector"),
        "industry": profile.get("industry"),
        "country": profile.get("country"),
        "currency": profile.get("currency"),
        "exchange": profile.get("exchange"),
        "market_cap": to_int_or_none(profile.get("marketCap")),
    }
    return connection.execute(UPSERT_STOCK_SQL, payload).scalar_one()


def _number_or_none(value, converter=float):
    if value is None or pd.isna(value) or not np.isfinite(float(value)):
        return None
    return converter(value)


def load_prices_to_database(
    connection: Connection,
    stock_id: int,
    prices: pd.DataFrame,
    replace_existing: bool = False,
) -> None:
    if replace_existing:
        connection.execute(
            text("DELETE FROM fact_stock_features WHERE stock_id = :stock_id"),
            {"stock_id": stock_id},
        )
        connection.execute(
            text("DELETE FROM fact_stock_price WHERE stock_id = :stock_id"),
            {"stock_id": stock_id},
        )

    database_columns = [
        "trade_date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "dividends",
        "stock_splits",
    ]
    records = []
    for row in prices[database_columns].to_dict(orient="records"):
        records.append(
            {
                "stock_id": stock_id,
                "trade_date": row["trade_date"],
                "open_price": _number_or_none(row["open_price"]),
                "high_price": _number_or_none(row["high_price"]),
                "low_price": _number_or_none(row["low_price"]),
                "close_price": _number_or_none(row["close_price"]),
                "volume": _number_or_none(row["volume"], int),
                "dividends": _number_or_none(row["dividends"]),
                "stock_splits": _number_or_none(row["stock_splits"]),
            }
        )

    if records:
        connection.execute(UPSERT_PRICE_SQL, records)


def process_ticker(
    ticker_symbol: str,
    engine: Engine | None = None,
    write_database: bool = True,
    replace_existing: bool = False,
) -> pd.DataFrame:
    """Clean, persist and optionally load the latest snapshot for one ticker."""

    prices = clean_price_data(ticker_symbol)
    processed_file = save_processed_prices(ticker_symbol, prices)
    print(f"{ticker_symbol}: saved {len(prices)} rows to {processed_file}")

    if write_database:
        profile = load_profile(ticker_symbol)
        database_engine = engine or get_engine()
        with database_engine.begin() as connection:
            stock_id = get_stock_id(connection, ticker_symbol, profile)
            load_prices_to_database(
                connection,
                stock_id,
                prices,
                replace_existing=replace_existing,
            )
        print(f"{ticker_symbol}: loaded {len(prices)} database rows")

    return prices


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean Yahoo Finance raw snapshots")
    parser.add_argument("--tickers", nargs="+", default=list(TICKERS))
    parser.add_argument("--no-database", action="store_true")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace existing price and feature rows for the selected tickers.",
    )
    args = parser.parse_args()

    engine = None if args.no_database else get_engine()
    for ticker_symbol in args.tickers:
        process_ticker(
            ticker_symbol,
            engine=engine,
            write_database=not args.no_database,
            replace_existing=args.replace,
        )


if __name__ == "__main__":
    main()
