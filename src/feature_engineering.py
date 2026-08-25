from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

try:
    from .config import FEATURE_DIR, PROCESSED_PRICE_DIR
    from .database import get_engine
except ImportError:  # Allows: python src/feature_engineering.py
    from config import FEATURE_DIR, PROCESSED_PRICE_DIR
    from database import get_engine


FEATURE_COLUMNS = [
    "daily_return",
    "moving_average_7",
    "moving_average_30",
    "volatility_30",
    "momentum_7",
    "volume_change",
]

UPSERT_FEATURE_SQL = text(
    """
    INSERT INTO fact_stock_features (
        stock_id, trade_date, daily_return, moving_average_7,
        moving_average_30, volatility_30, momentum_7,
        volume_change, target_next_day_up
    )
    VALUES (
        :stock_id, :trade_date, :daily_return, :moving_average_7,
        :moving_average_30, :volatility_30, :momentum_7,
        :volume_change, :target_next_day_up
    )
    ON CONFLICT (stock_id, trade_date)
    DO UPDATE SET
        daily_return = EXCLUDED.daily_return,
        moving_average_7 = EXCLUDED.moving_average_7,
        moving_average_30 = EXCLUDED.moving_average_30,
        volatility_30 = EXCLUDED.volatility_30,
        momentum_7 = EXCLUDED.momentum_7,
        volume_change = EXCLUDED.volume_change,
        target_next_day_up = EXCLUDED.target_next_day_up;
    """
)


def load_processed_prices() -> pd.DataFrame:
    """Load and combine all curated per-ticker price files."""

    files = sorted(PROCESSED_PRICE_DIR.glob("*_clean.csv"))
    if not files:
        raise FileNotFoundError(
            f"No processed price files found in {PROCESSED_PRICE_DIR}."
        )

    frames = [pd.read_csv(path, parse_dates=["trade_date"]) for path in files]
    return pd.concat(frames, ignore_index=True).sort_values(
        ["ticker", "trade_date"]
    )


def calculate_features(prices: pd.DataFrame) -> pd.DataFrame:
    """Calculate leakage-safe, per-ticker time-series features and target."""

    required_columns = {"ticker", "trade_date", "close_price", "volume"}
    missing_columns = sorted(required_columns.difference(prices.columns))
    if missing_columns:
        raise ValueError("Missing processed columns: " + ", ".join(missing_columns))

    frame = prices.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    frame = frame.dropna(subset=["ticker", "trade_date", "close_price"])
    frame = frame.sort_values(["ticker", "trade_date"]).reset_index(drop=True)

    grouped = frame.groupby("ticker", group_keys=False)
    frame["daily_return"] = grouped["close_price"].transform(
        lambda values: values.pct_change(fill_method=None)
    )
    frame["moving_average_7"] = grouped["close_price"].transform(
        lambda values: values.rolling(7, min_periods=7).mean()
    )
    frame["moving_average_30"] = grouped["close_price"].transform(
        lambda values: values.rolling(30, min_periods=30).mean()
    )
    frame["volatility_30"] = frame.groupby("ticker")["daily_return"].transform(
        lambda values: values.rolling(30, min_periods=30).std()
    )
    frame["momentum_7"] = grouped["close_price"].transform(
        lambda values: values.pct_change(7, fill_method=None)
    )
    frame["volume_change"] = grouped["volume"].transform(
        lambda values: values.pct_change(fill_method=None)
    )
    frame["volume_change"] = frame["volume_change"].replace(
        [np.inf, -np.inf], np.nan
    )

    next_close = grouped["close_price"].shift(-1)
    target = pd.Series(pd.NA, index=frame.index, dtype="boolean")
    known_target = next_close.notna()
    target.loc[known_target] = (
        next_close.loc[known_target] > frame.loc[known_target, "close_price"]
    )
    frame["target_next_day_up"] = target

    output_columns = [
        "ticker",
        "trade_date",
        *FEATURE_COLUMNS,
        "target_next_day_up",
    ]
    return frame[output_columns]


def save_features(features: pd.DataFrame) -> str:
    FEATURE_DIR.mkdir(parents=True, exist_ok=True)
    output_file = FEATURE_DIR / "stock_features.csv"
    features.to_csv(output_file, index=False)
    return str(output_file)


def _number_or_none(value):
    if value is None or pd.isna(value) or not np.isfinite(float(value)):
        return None
    return float(value)


def load_features_to_database(
    connection: Connection,
    features: pd.DataFrame,
    replace_existing: bool = False,
) -> int:
    """Upsert calculated features for all tickers present in the frame."""

    ticker_rows = connection.execute(
        text("SELECT stock_id, ticker FROM dim_stock")
    ).mappings()
    stock_ids = {row["ticker"]: row["stock_id"] for row in ticker_rows}
    missing_tickers = sorted(set(features["ticker"]).difference(stock_ids))
    if missing_tickers:
        raise ValueError(
            "Tickers missing from dim_stock: " + ", ".join(missing_tickers)
        )

    selected_stock_ids = [stock_ids[ticker] for ticker in features["ticker"].unique()]
    if replace_existing:
        connection.execute(
            text("DELETE FROM fact_stock_features WHERE stock_id = ANY(:stock_ids)"),
            {"stock_ids": selected_stock_ids},
        )

    records = []
    for row in features.to_dict(orient="records"):
        target = row["target_next_day_up"]
        records.append(
            {
                "stock_id": stock_ids[row["ticker"]],
                "trade_date": pd.Timestamp(row["trade_date"]).date(),
                **{column: _number_or_none(row[column]) for column in FEATURE_COLUMNS},
                "target_next_day_up": (
                    None if pd.isna(target) else bool(target)
                ),
            }
        )

    if records:
        connection.execute(UPSERT_FEATURE_SQL, records)
    return len(records)


def build_features(
    engine: Engine | None = None,
    write_database: bool = True,
    replace_existing: bool = False,
) -> pd.DataFrame:
    """Build the complete feature layer from processed local files."""

    features = calculate_features(load_processed_prices())
    output_file = save_features(features)
    print(f"Saved {len(features)} feature rows to {output_file}")

    if write_database:
        database_engine = engine or get_engine()
        with database_engine.begin() as connection:
            row_count = load_features_to_database(
                connection,
                features,
                replace_existing=replace_existing,
            )
        print(f"Loaded {row_count} feature rows into PostgreSQL")

    return features


def main() -> None:
    parser = argparse.ArgumentParser(description="Build stock time-series features")
    parser.add_argument("--no-database", action="store_true")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    build_features(
        write_database=not args.no_database,
        replace_existing=args.replace,
    )


if __name__ == "__main__":
    main()
