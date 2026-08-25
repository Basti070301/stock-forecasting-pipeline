from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, URL

try:
    from .config import PROJECT_ROOT
except ImportError:  # Allows: python src/database.py
    from config import PROJECT_ROOT


load_dotenv(PROJECT_ROOT / ".env")


def get_engine() -> Engine:
    """Create a validated SQLAlchemy connection pool for PostgreSQL."""

    required_variables = (
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
    )
    missing_variables = [name for name in required_variables if not os.getenv(name)]

    if missing_variables:
        raise RuntimeError(
            "Folgende Umgebungsvariablen fehlen in der .env-Datei: "
            + ", ".join(missing_variables)
        )

    database_url = URL.create(
        drivername="postgresql+psycopg2",
        username=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME"),
    )

    return create_engine(database_url, pool_pre_ping=True)


def initialize_database(engine: Engine | None = None) -> None:
    """Create the project tables and indexes if they do not exist."""

    database_engine = engine or get_engine()
    schema_sql = (PROJECT_ROOT / "sql" / "create_tables.sql").read_text(
        encoding="utf-8"
    )

    with database_engine.begin() as connection:
        connection.exec_driver_sql(schema_sql)


def database_status(engine: Engine | None = None) -> dict[str, int]:
    """Return row counts for the project tables."""

    database_engine = engine or get_engine()
    available_tables = set(inspect(database_engine).get_table_names())
    table_names = ("dim_stock", "fact_stock_price", "fact_stock_features")
    status: dict[str, int] = {}

    with database_engine.connect() as connection:
        for table_name in table_names:
            if table_name in available_tables:
                status[table_name] = connection.execute(
                    text(f"SELECT COUNT(*) FROM {table_name}")
                ).scalar_one()

    return status


def test_connection(engine: Engine | None = None) -> None:
    """Raise an exception unless PostgreSQL can execute a simple query."""

    database_engine = engine or get_engine()

    with database_engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def main() -> None:
    parser = argparse.ArgumentParser(description="PostgreSQL setup and status check")
    parser.add_argument(
        "--init",
        action="store_true",
        help="Create missing project tables and indexes.",
    )
    args = parser.parse_args()

    engine = get_engine()
    test_connection(engine)
    print("Database connection successful.")

    if args.init:
        initialize_database(engine)
        print("Database schema initialized.")

    for table_name, row_count in database_status(engine).items():
        print(f"{table_name}: {row_count} rows")


if __name__ == "__main__":
    main()
