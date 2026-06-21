from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf
from sqlalchemy import text

from database import get_engine


# Die fünf Aktien für den ersten Proof of Concept
STOCKS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "SAP.DE",
    "ALV.DE",
]

PROJECT_ROOT = Path(__file__).resolve().parents[1]

RAW_PRICE_DIR = PROJECT_ROOT / "data" / "raw" / "prices"
RAW_PROFILE_DIR = PROJECT_ROOT / "data" / "raw" / "profile"

RUN_TIMESTAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


UPSERT_STOCK_SQL = text(
    """
    INSERT INTO dim_stock (
        ticker,
        company_name,
        sector,
        industry,
        country,
        currency,
        exchange,
        market_cap
    )
    VALUES (
        :ticker,
        :company_name,
        :sector,
        :industry,
        :country,
        :currency,
        :exchange,
        :market_cap
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
        stock_id,
        trade_date,
        open_price,
        high_price,
        low_price,
        close_price,
        volume,
        dividends,
        stock_splits
    )
    VALUES (
        :stock_id,
        :trade_date,
        :open_price,
        :high_price,
        :low_price,
        :close_price,
        :volume,
        :dividends,
        :stock_splits
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


def as_float(value):
    """Konvertiert Werte sicher zu float oder None."""

    if value is None or pd.isna(value):
        return None

    return float(value)


def as_int(value):
    """Konvertiert Werte sicher zu int oder None."""

    if value is None or pd.isna(value):
        return None

    return int(value)


def prepare_directories() -> None:
    """Erstellt die benötigten Raw-Data-Ordner."""

    RAW_PRICE_DIR.mkdir(parents=True, exist_ok=True)
    RAW_PROFILE_DIR.mkdir(parents=True, exist_ok=True)


def save_raw_data(
    ticker_symbol: str,
    info: dict,
    history: pd.DataFrame,
) -> None:
    """
    Speichert API-Rohdaten unverändert als CSV bzw. JSON.
    """

    safe_ticker = ticker_symbol.replace(".", "_")

    price_file = RAW_PRICE_DIR / f"{safe_ticker}_{RUN_TIMESTAMP}.csv"
    profile_file = RAW_PROFILE_DIR / f"{safe_ticker}_{RUN_TIMESTAMP}.json"

    history.to_csv(price_file)

    with open(profile_file, "w", encoding="utf-8") as file:
        json.dump(
            info,
            file,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

    logging.info("Raw data saved for %s", ticker_symbol)


def get_stock_id(connection, ticker_symbol: str, info: dict) -> int:
    """
    Fügt Stammdaten ein oder aktualisiert sie und gibt die stock_id zurück.
    """

    payload = {
        "ticker": ticker_symbol,
        "company_name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "country": info.get("country"),
        "currency": info.get("currency"),
        "exchange": info.get("exchange"),
        "market_cap": as_int(info.get("marketCap")),
    }

    result = connection.execute(UPSERT_STOCK_SQL, payload)

    return result.scalar_one()


def prepare_price_rows(
    history: pd.DataFrame,
    stock_id: int,
) -> list[dict]:
    """
    Bereitet Kursdaten für den Datenbankimport vor.
    """

    prices = history.reset_index().copy()

    date_column = "Date"

    if date_column not in prices.columns:
        date_column = "Datetime"

    prices["trade_date"] = pd.to_datetime(
        prices[date_column],
        utc=True,
    ).dt.date

    required_columns = [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
        "Dividends",
        "Stock Splits",
    ]

    for column in required_columns:
        if column not in prices.columns:
            prices[column] = 0

    prices = prices.dropna(subset=["trade_date", "Close"])

    rows = []

    for row in prices.to_dict(orient="records"):
        rows.append(
            {
                "stock_id": stock_id,
                "trade_date": row["trade_date"],
                "open_price": as_float(row["Open"]),
                "high_price": as_float(row["High"]),
                "low_price": as_float(row["Low"]),
                "close_price": as_float(row["Close"]),
                "volume": as_int(row["Volume"]),
                "dividends": as_float(row["Dividends"]),
                "stock_splits": as_float(row["Stock Splits"]),
            }
        )

    return rows


def load_ticker(ticker_symbol: str) -> None:
    """
    Lädt Stammdaten und historische Kursdaten einer Aktie.
    """

    logging.info("Loading data for %s", ticker_symbol)

    ticker = yf.Ticker(ticker_symbol)

    # Stammdaten abrufen
    info = ticker.info or {}

    # Fünf Jahre tägliche Kursdaten abrufen
    history = ticker.history(
        period="5y",
        interval="1d",
        auto_adjust=True,
        actions=True,
    )

    if history.empty:
        raise ValueError(
            f"No historical price data received for {ticker_symbol}."
        )

    # Rohdaten speichern
    save_raw_data(
        ticker_symbol=ticker_symbol,
        info=info,
        history=history,
    )

    engine = get_engine()

    with engine.begin() as connection:
        stock_id = get_stock_id(
            connection=connection,
            ticker_symbol=ticker_symbol,
            info=info,
        )

        price_rows = prepare_price_rows(
            history=history,
            stock_id=stock_id,
        )

        connection.execute(
            UPSERT_PRICE_SQL,
            price_rows,
        )

    logging.info(
        "%s: %s daily price records loaded.",
        ticker_symbol,
        len(price_rows),
    )


def main() -> None:
    """
    Startpunkt für die Initialbefüllung.
    """

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    prepare_directories()

    successful_tickers = []
    failed_tickers = []

    for ticker_symbol in STOCKS:
        try:
            load_ticker(ticker_symbol)
            successful_tickers.append(ticker_symbol)

        except Exception as error:
            logging.exception(
                "Loading failed for %s: %s",
                ticker_symbol,
                error,
            )
            failed_tickers.append(ticker_symbol)

        # Kleine Pause zwischen den API-Abfragen
        time.sleep(1)

    print("\nInitial load finished.")
    print(f"Successful: {successful_tickers}")

    if failed_tickers:
        print(f"Failed: {failed_tickers}")


if __name__ == "__main__":
    main()