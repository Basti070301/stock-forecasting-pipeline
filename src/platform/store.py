"""Only additive tables. Migration must be requested explicitly in live mode."""

import argparse
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Column, MetaData, String, Table, create_engine, insert, select, update
from sqlalchemy.exc import IntegrityError

from src.database import get_engine

from .config import DEFAULT_INSTRUMENTS, Settings

metadata = MetaData()


def document_table(name):
    return Table(
        name,
        metadata,
        Column("id", String(128), primary_key=True),
        Column("mode", String(8), nullable=False, index=True),
        Column("created_at", String(40), nullable=False),
        Column("payload", JSON, nullable=False),
    )


TABLES = {
    name: document_table("si_" + name)
    for name in (
        "schema_versions",
        "instruments",
        "news",
        "news_links",
        "sentiments",
        "models",
        "forecasts",
        "outcomes",
        "backtests",
        "jobs",
        "intraday_prices",
        "provider_calls",
    )
}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, settings: Settings, engine=None):
        self.settings = settings
        if engine is not None:
            self.engine = engine
        elif settings.mode == "live":
            self.engine = get_engine()
        else:
            settings.runtime_dir.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(
                f"sqlite:///{settings.runtime_dir / 'demo.sqlite'}",
                connect_args={"check_same_thread": False},
            )

    def migrate(self):
        # v1 only creates missing si_ tables; existing PoC schema is never modified.
        metadata.create_all(self.engine)
        self.add(
            "schema_versions", {"version": 1, "description": "Additive intelligence tables"}, "v1"
        )
        for item in DEFAULT_INSTRUMENTS:
            self.add("instruments", item.model_dump(), item.ticker)

    def add(self, name, payload, identity=None):
        identity = identity or str(uuid4())
        table = TABLES[name]
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    insert(table).values(
                        id=f"{self.settings.mode}:{identity}",
                        mode=self.settings.mode,
                        created_at=utcnow(),
                        payload=payload,
                    )
                )
        except IntegrityError:
            if self.get(name, identity) is None:
                raise
        return identity

    def get(self, name, identity):
        table = TABLES[name]
        with self.engine.connect() as conn:
            row = (
                conn.execute(select(table).where(table.c.id == f"{self.settings.mode}:{identity}"))
                .mappings()
                .first()
            )
        return self._record(row) if row else None

    @staticmethod
    def _record(row):
        return {**row["payload"], "id": row["id"].split(":", 1)[1], "created_at": row["created_at"]}

    def list(self, name, limit=1000):
        table = TABLES[name]
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    select(table)
                    .where(table.c.mode == self.settings.mode)
                    .order_by(table.c.created_at.desc())
                    .limit(limit)
                )
                .mappings()
                .all()
            )
        return [self._record(row) for row in rows]

    def update(self, name, identity, payload):
        if name not in {"jobs", "instruments"}:
            raise ValueError("Unveränderliche Forschungsdaten; Ergebnis separat speichern")
        table = TABLES[name]
        with self.engine.begin() as conn:
            conn.execute(
                update(table)
                .where(table.c.id == f"{self.settings.mode}:{identity}")
                .values(payload=payload)
            )

    def instruments(self):
        return sorted(self.list("instruments", 100), key=lambda x: x["ticker"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Additive si_ Schema-Migration v1")
    parser.add_argument("--migrate", action="store_true", required=True)
    parser.parse_args()
    Store(Settings()).migrate()
    print("Migration v1 angewendet; bestehende Tabellen unverändert.")
