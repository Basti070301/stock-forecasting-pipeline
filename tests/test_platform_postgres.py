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
