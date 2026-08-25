from __future__ import annotations

import argparse
import logging

from .config import TICKERS
from .database import database_status, get_engine, initialize_database
from .feature_engineering import build_features
from .ingestion import run_ingestion
from .model_baseline import train_baseline
from .preprocessing import process_ticker


def run_pipeline(
    tickers: list[str] | tuple[str, ...] = TICKERS,
    ingest: bool = False,
    period: str = "5y",
    write_database: bool = True,
    replace_existing: bool = False,
) -> dict:
    """Run raw ingestion (optional), cleaning, features and baseline model."""

    if ingest:
        results = run_ingestion(tickers, period)
        failures = {ticker: result for ticker, result in results.items() if result != "ok"}
        if failures:
            raise RuntimeError(f"Ingestion failures: {failures}")

    engine = get_engine() if write_database else None
    if engine is not None:
        initialize_database(engine)

    for ticker_symbol in tickers:
        process_ticker(
            ticker_symbol,
            engine=engine,
            write_database=write_database,
            replace_existing=replace_existing,
        )

    features = build_features(
        engine=engine,
        write_database=write_database,
        replace_existing=replace_existing,
    )
    _, metrics, _ = train_baseline()

    return {
        "feature_rows": len(features),
        "metrics": metrics,
        "database": database_status(engine) if engine is not None else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the stock forecasting pipeline")
    parser.add_argument("--tickers", nargs="+", default=list(TICKERS))
    parser.add_argument("--ingest", action="store_true")
    parser.add_argument("--period", default="5y")
    parser.add_argument("--no-database", action="store_true")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Rebuild selected price and feature rows from the latest raw snapshot.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    result = run_pipeline(
        tickers=args.tickers,
        ingest=args.ingest,
        period=args.period,
        write_database=not args.no_database,
        replace_existing=args.replace,
    )

    print("\nPipeline finished successfully")
    print(f"Feature rows: {result['feature_rows']}")
    print(f"ROC-AUC: {result['metrics']['roc_auc']:.4f}")
    if result["database"]:
        for table_name, row_count in result["database"].items():
            print(f"{table_name}: {row_count} rows")


if __name__ == "__main__":
    main()
