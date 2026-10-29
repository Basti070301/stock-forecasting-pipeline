"""Runs only against an explicitly provisioned disposable test database (CI)."""

import os

import pytest
from sqlalchemy import text

from src.database import get_engine, initialize_database
from src.platform.config import Settings
from src.platform.store import Store


@pytest.mark.skipif(
    os.getenv("SI_TEST_POSTGRES") != "1", reason="Keine explizite PostgreSQL-Testdatenbank"
)
def test_additive_postgres_migration_and_immutable_records():
    engine = get_engine()
    initialize_database(engine)
    store = Store(Settings(mode="live"), engine=engine)
    store.migrate()
    store.migrate()
    store.add("forecasts", {"ticker": "AAPL", "probability": 0.51}, "ci-immutable")
    store.add("forecasts", {"ticker": "AAPL", "probability": 0.99}, "ci-immutable")
    assert store.get("forecasts", "ci-immutable")["probability"] == 0.51
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM dim_stock")).scalar_one() >= 0
    engine.dispose()


@pytest.mark.skipif(
    os.getenv("SI_TEST_POSTGRES") != "1", reason="Keine explizite PostgreSQL-Testdatenbank"
)
def test_deployment_migration_seed_and_existing_data_preserved():
    from src.config import PROJECT_ROOT
    from src.platform.maintenance import import_reference, migrate

    engine = get_engine()
    migrate(engine)
    first = import_reference(engine, PROJECT_ROOT / "data" / "raw")
    with engine.connect() as conn:
        before = (
            conn.execute(
                text(
                    "SELECT stock_id, trade_date, close_price FROM fact_stock_price ORDER BY price_id LIMIT 1"
                )
            )
            .mappings()
            .one()
        )
    # A different pre-existing price must survive every repeated seed/migration.
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE fact_stock_price SET close_price=123.4567 WHERE stock_id=:stock_id AND trade_date=:trade_date"
            ),
            before,
        )
    try:
        migrate(engine)
        second = import_reference(engine, PROJECT_ROOT / "data" / "raw")
        assert second == {"stocks": 0, "prices": 0, "features": 0}
        with engine.connect() as conn:
            assert (
                float(
                    conn.execute(
                        text(
                            "SELECT close_price FROM fact_stock_price WHERE stock_id=:stock_id AND trade_date=:trade_date"
                        ),
                        before,
                    ).scalar_one()
                )
                == 123.4567
            )
            assert (
                conn.execute(text("SELECT count(*) FROM si_deployment_migrations")).scalar_one()
                == 4
            )
        assert first["prices"] >= 0
    finally:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE fact_stock_price SET close_price=:close_price WHERE stock_id=:stock_id AND trade_date=:trade_date"
                ),
                before,
            )
        engine.dispose()
