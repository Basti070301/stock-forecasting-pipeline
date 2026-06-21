from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from database import get_engine


TICKERS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "SAP.DE",
    "ALV.DE",
]

PROJECT_ROOT = Path(__file__).resolve().parents[1]

RAW_PRICE_DIR = PROJECT_ROOT / "data" / "raw" / "prices"
RAW_PROFILE_DIR = PROJECT_ROOT / "data" / "raw" / "profiles"
PROCESSED_PRICE_DIR = PROJECT_ROOT / "data" / "processed" / "prices"


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


def get_file_stem(ticker_symbol: str) -> str:
    """
    SAP.DE wird zu SAP_DE, damit die Dateinamen einheitlich bleiben.
    """

    return ticker_symbol.replace(".", "_")


def create_directories() -> None:
    """
    Erstellt den Processed-Data-Ordner.
    """

    PROCESSED_PRICE_DIR.mkdir(parents=True, exist_ok=True)


def load_profile(ticker_symbol: str) -> dict:
    """
    Liest die gespeicherten Stammdaten aus der JSON-Datei.
    """

    file_stem = get_file_stem(ticker_symbol)
    profile_file = RAW_PROFILE_DIR / f"{file_stem}.json"

    with open(profile_file, "r", encoding="utf-8") as file:
        profile_payload = json.load(file)

    return profile_payload.get("data", {})


def clean_price_data(ticker_symbol: str) -> pd.DataFrame:
    """
    Liest Kursdaten aus dem Raw Layer und bereinigt sie.
    """

    file_stem = get_file_stem(ticker_symbol)
    raw_price_file = RAW_PRICE_DIR / f"{file_stem}.csv"

    prices = pd.read_csv(raw_price_file)

    # Je nach Abruf kann die Zeitspalte Date oder Datetime heißen.
    date_column = "Date" if "Date" in prices.columns else "Datetime"

    prices["trade_date"] = pd.to_datetime(
        prices[date_column],
        utc=True,
        errors="coerce",
    ).dt.date

    # Einheitliche Datenbank-Spaltennamen
    prices = prices.rename(
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

    # Ticker-Spalte ergänzen
    prices["ticker"] = ticker_symbol

    required_columns = [
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

    # Fehlende Spalten absichern
    for column in required_columns:
        if column not in prices.columns:
            prices[column] = None

    prices = prices[required_columns].copy()

    # Datentypen bereinigen
    numeric_columns = [
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "dividends",
        "stock_splits",
    ]

    for column in numeric_columns:
        prices[column] = pd.to_numeric(
            prices[column],
            errors="coerce",
        )

    # Nicht verwendbare Datensätze entfernen
    prices = prices.dropna(
        subset=[
            "trade_date",
            "close_price",
        ]
    )

    # Doppelte Aktie-Datum-Kombinationen entfernen
    prices = prices.drop_duplicates(
        subset=[
            "ticker",
            "trade_date",
        ],
        keep="last",
    )

    # Sortierung für saubere Zeitreihen
    prices = prices.sort_values(
        by=[
            "ticker",
            "trade_date",
        ]
    ).reset_index(drop=True)

    return prices


def save_processed_prices(
    ticker_symbol: str,
    prices: pd.DataFrame,
) -> None:
    """
    Speichert die bereinigten Kursdaten als CSV.
    """

    file_stem = get_file_stem(ticker_symbol)
    processed_file = PROCESSED_PRICE_DIR / f"{file_stem}_clean.csv"

    prices.to_csv(
        processed_file,
        index=False,
    )

    print(f"  Processed file saved: {processed_file}")


def to_int_or_none(value) -> int | None:
    """
    Wandelt Werte sicher in Integer um.
    """

    if value is None or pd.isna(value):
        return None

    return int(value)


def get_stock_id(
    connection,
    ticker_symbol: str,
    profile: dict,
) -> int:
    """
    Fügt Stammdaten in dim_stock ein oder aktualisiert sie.
    Gibt anschließend die stock_id zurück.
    """

    payload = {
        "ticker": ticker_symbol,
        "company_name": profile.get("longName")
        or profile.get("shortName"),
        "sector": profile.get("sector"),
        "industry": profile.get("industry"),
        "country": profile.get("country"),
        "currency": profile.get("currency"),
        "exchange": profile.get("exchange"),
        "market_cap": to_int_or_none(profile.get("marketCap")),
    }

    result = connection.execute(
        UPSERT_STOCK_SQL,
        payload,
    )

    return result.scalar_one()


def load_prices_to_database(
    connection,
    stock_id: int,
    prices: pd.DataFrame,
) -> None:
    """
    Lädt bereinigte Kursdaten in fact_stock_price.
    """

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
        record = {
            "stock_id": stock_id,
            "trade_date": row["trade_date"],
            "open_price": (
                float(row["open_price"])
                if pd.notna(row["open_price"])
                else None
            ),
            "high_price": (
                float(row["high_price"])
                if pd.notna(row["high_price"])
                else None
            ),
            "low_price": (
                float(row["low_price"])
                if pd.notna(row["low_price"])
                else None
            ),
            "close_price": (
                float(row["close_price"])
                if pd.notna(row["close_price"])
                else None
            ),
            "volume": (
                int(row["volume"])
                if pd.notna(row["volume"])
                else None
            ),
            "dividends": (
                float(row["dividends"])
                if pd.notna(row["dividends"])
                else None
            ),
            "stock_splits": (
                float(row["stock_splits"])
                if pd.notna(row["stock_splits"])
                else None
            ),
        }

        records.append(record)

    connection.execute(
        UPSERT_PRICE_SQL,
        records,
    )


def process_ticker(ticker_symbol: str) -> None:
    """
    Führt Preprocessing, lokale Speicherung und PostgreSQL-Import
    für eine Aktie durch.
    """

    print(f"\nProcessing {ticker_symbol} ...")

    profile = load_profile(ticker_symbol)
    prices = clean_price_data(ticker_symbol)

    save_processed_prices(
        ticker_symbol=ticker_symbol,
        prices=prices,
    )

    engine = get_engine()

    with engine.begin() as connection:
        stock_id = get_stock_id(
            connection=connection,
            ticker_symbol=ticker_symbol,
            profile=profile,
        )

        load_prices_to_database(
            connection=connection,
            stock_id=stock_id,
            prices=prices,
        )

    print(f"  Database rows loaded: {len(prices)}")


def main() -> None:
    """
    Startpunkt des Preprocessing-Schritts.
    """

    create_directories()

    for ticker_symbol in TICKERS:
        process_ticker(ticker_symbol)

    print("\nPreprocessing and database loading finished.")


if __name__ == "__main__":
    main()