"""Explicit host-only deployment maintenance. Never invoked automatically at startup."""

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd
from sqlalchemy import MetaData, Table, select, text
from sqlalchemy.dialects.postgresql import insert

from src.config import PROJECT_ROOT
from src.database import get_engine
from src.feature_engineering import FEATURE_COLUMNS, calculate_features
from src.preprocessing import _number_or_none, clean_price_frame

from .config import DEFAULT_INSTRUMENTS, Settings
from .store import TABLES, Store, utcnow


def migrate(engine, reader_password=None):
    """Atomic, advisory-locked, checksummed additive migrations for PostgreSQL."""
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(72222001)"))
        conn.exec_driver_sql("""CREATE TABLE IF NOT EXISTS si_deployment_migrations (
            version VARCHAR(80) PRIMARY KEY, sha256 VARCHAR(64) NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        for path in sorted((PROJECT_ROOT / "sql" / "migrations").glob("*.sql")):
            source = path.read_text(encoding="utf-8").replace("\r\n", "\n")
            checksum = hashlib.sha256(source.encode()).hexdigest()
            previous = conn.execute(
                text("SELECT sha256 FROM si_deployment_migrations WHERE version=:v"),
                {"v": path.name},
            ).scalar_one_or_none()
            if previous and previous != checksum:
                raise ValueError(f"Migration {path.name} nachträglich verändert; Abbruch")
            if previous is None:
                conn.exec_driver_sql(source)
                conn.execute(
                    text("INSERT INTO si_deployment_migrations (version, sha256) VALUES (:v,:h)"),
                    {"v": path.name, "h": checksum},
                )
        for version in (1, 2, 3):
            conn.execute(
                insert(TABLES["schema_versions"])
                .values(
                    id=f"live:v{version}",
                    mode="live",
                    created_at=utcnow(),
                    payload={
                        "version": version,
                        "description": "Additive versioned deployment schema",
                    },
                )
                .on_conflict_do_nothing()
            )
        for instrument in DEFAULT_INSTRUMENTS:
            conn.execute(
                insert(TABLES["instruments"])
                .values(
                    id=f"live:{instrument.ticker}",
                    mode="live",
                    created_at=utcnow(),
                    payload=instrument.model_dump(),
                )
                .on_conflict_do_nothing()
            )
        if reader_password:
            # Driver binding quotes the password; never interpolate it or log exceptions.
            exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname='si_reader'")).scalar()
            if not exists:
                conn.exec_driver_sql(
                    "CREATE ROLE si_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %s",
                    (reader_password,),
                )
            unsafe_role = conn.execute(
                text("""SELECT
                rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls
                OR EXISTS (SELECT 1 FROM pg_auth_members WHERE member=pg_roles.oid)
                FROM pg_roles WHERE rolname='si_reader'""")
            ).scalar_one()
            unsafe_tables = conn.execute(
                text("""SELECT EXISTS (
                SELECT 1 FROM pg_tables WHERE schemaname='public'
                AND has_table_privilege('si_reader', quote_ident(schemaname)||'.'||quote_ident(tablename),
                    'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'))""")
            ).scalar_one()
            unsafe_schema = conn.execute(
                text("SELECT has_schema_privilege('si_reader', 'public', 'CREATE')")
            ).scalar_one()
            if unsafe_role or unsafe_tables or unsafe_schema:
                raise ValueError(
                    "Vorhandene Rolle si_reader hat erhöhte Rechte; manuelle Prüfung erforderlich"
                )
            conn.exec_driver_sql("GRANT CONNECT ON DATABASE stockintel TO si_reader")
            conn.exec_driver_sql("GRANT USAGE ON SCHEMA public TO si_reader")
            conn.exec_driver_sql("GRANT SELECT ON ALL TABLES IN SCHEMA public TO si_reader")
            conn.exec_driver_sql(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO si_reader"
            )


def import_reference(engine, raw=None):
    """Insert missing rows only, one transaction. Existing prices/features are never replaced."""
    raw = Path(raw or PROJECT_ROOT / "reference" / "raw")
    if not raw.exists():
        raise ValueError("Referenzpfad fehlt; lokal --raw data/raw angeben")
    snapshot = "20260825T213028Z"
    counts = {"stocks": 0, "prices": 0, "features": 0}
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(72222001)"))
        tables = {
            name: Table(name, MetaData(), autoload_with=conn)
            for name in ("dim_stock", "fact_stock_price", "fact_stock_features")
        }
        for instrument in DEFAULT_INSTRUMENTS:
            ticker = instrument.ticker
            stem = ticker.replace(".", "_")
            frame = clean_price_frame(
                pd.read_csv(raw / "prices" / f"{stem}_{snapshot}.csv"), ticker
            )
            payload = json.loads(
                (raw / "profiles" / f"{stem}_{snapshot}.json").read_text(encoding="utf-8")
            )
            profile = payload.get("data", payload)
            result = conn.execute(
                insert(tables["dim_stock"])
                .values(
                    ticker=ticker,
                    company_name=profile.get("longName", instrument.company),
                    sector=profile.get("sector"),
                    industry=profile.get("industry"),
                    country=profile.get("country"),
                    currency=profile.get("currency"),
                    exchange=profile.get("exchange"),
                    market_cap=profile.get("marketCap"),
                )
                .on_conflict_do_nothing(index_elements=["ticker"])
            )
            counts["stocks"] += result.rowcount
            stock_id = conn.execute(
                select(tables["dim_stock"].c.stock_id).where(tables["dim_stock"].c.ticker == ticker)
            ).scalar_one()
            rows = []
            for row in frame.to_dict("records"):
                rows.append(
                    {
                        "stock_id": stock_id,
                        "trade_date": row["trade_date"],
                        **{
                            key: _number_or_none(value, int if key == "volume" else float)
                            for key, value in row.items()
                            if key not in {"ticker", "trade_date"}
                        },
                    }
                )
            for row in rows:
                counts["prices"] += conn.execute(
                    insert(tables["fact_stock_price"])
                    .values(**row)
                    .on_conflict_do_nothing(index_elements=["stock_id", "trade_date"])
                ).rowcount
            # Calculate missing features from the actual retained database prices.
            prices = pd.read_sql(
                select(tables["fact_stock_price"]).where(
                    tables["fact_stock_price"].c.stock_id == stock_id
                ),
                conn,
            )
            prices["ticker"] = ticker
            for row in calculate_features(prices).to_dict("records"):
                target = row["target_next_day_up"]
                values = {
                    "stock_id": stock_id,
                    "trade_date": row["trade_date"].date(),
                    **{key: _number_or_none(row[key]) for key in FEATURE_COLUMNS},
                    "target_next_day_up": None if pd.isna(target) else bool(target),
                }
                counts["features"] += conn.execute(
                    insert(tables["fact_stock_features"])
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=["stock_id", "trade_date"])
                ).rowcount
    return counts


def check_writes():
    directories = [
        Settings().runtime_dir,
        PROJECT_ROOT / "data",
        Path(os.environ.get("HF_HOME", PROJECT_ROOT / ".cache" / "huggingface")),
    ]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=directory) as handle:
            handle.write(b"write-test")
    return {"writable": [str(path) for path in directories]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "init-db",
            "import-reference",
            "download-model",
            "check-model",
            "check-writes",
            "analyze-news",
        ],
    )
    parser.add_argument("--raw", type=Path)
    args = parser.parse_args()
    engine = None
    try:
        if args.command in {"init-db", "import-reference", "analyze-news"}:
            reader_password = os.environ.get("DB_PASSWORD")
            admin_password = os.environ.get("DB_ADMIN_PASSWORD")
            if not admin_password:
                raise ValueError(
                    "DB_ADMIN_PASSWORD muss für diesen expliziten Wartungsaufruf gesetzt sein"
                )
            os.environ.update(DB_USER="si_owner", DB_PASSWORD=admin_password)
            engine = get_engine()
            if args.command == "init-db":
                migrate(engine, reader_password)
                result = {"schema_version": 3}
            elif args.command == "import-reference":
                result = import_reference(engine, args.raw)
            else:
                from .news import analyze_pending

                result = analyze_pending(Store(Settings(mode="live"), engine=engine))
        elif args.command == "download-model":
            if os.environ.get("HF_HUB_OFFLINE", "0") != "0":
                raise ValueError("Download explizit mit HF_HUB_OFFLINE=0 erlauben")
            from huggingface_hub import snapshot_download

            from .news import FINBERT_REVISION, finbert_options

            snapshot_download(
                "ProsusAI/finbert",
                revision=FINBERT_REVISION,
                cache_dir=finbert_options()["cache_dir"],
                allow_patterns=[
                    "config.json",
                    "pytorch_model.bin",
                    "vocab.txt",
                    "tokenizer_config.json",
                    "special_tokens_map.json",
                ],
            )
            result = {"downloaded_revision": FINBERT_REVISION}
        elif args.command == "check-model":
            from .news import analyze, finbert

            article = {
                "id": "synthetic-smoke-only",
                "title": "The company reported higher revenue and profit.",
                "description": "",
                "language": "en",
            }
            result = {
                "synthetic_input": True,
                "result": analyze(article),
                "cache": finbert.cache_info()._asdict(),
            }
            analyze(article)
            result["cache_after_second_inference"] = finbert.cache_info()._asdict()
            if sys.platform != "win32":
                import resource

                result["process_peak_rss_mib"] = round(
                    resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1
                )
            else:
                import ctypes
                from ctypes import wintypes

                class MemoryCounters(ctypes.Structure):
                    _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                        (name, ctypes.c_size_t)
                        for name in (
                            "peak_working_set",
                            "working_set",
                            "peak_paged_pool",
                            "paged_pool",
                            "peak_nonpaged_pool",
                            "nonpaged_pool",
                            "pagefile",
                            "peak_pagefile",
                        )
                    ]

                counters = MemoryCounters()
                counters.cb = ctypes.sizeof(counters)
                current_process = ctypes.windll.kernel32.GetCurrentProcess
                current_process.restype = wintypes.HANDLE
                memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
                memory_info.argtypes = [
                    wintypes.HANDLE,
                    ctypes.POINTER(MemoryCounters),
                    wintypes.DWORD,
                ]
                if memory_info(current_process(), ctypes.byref(counters), counters.cb):
                    result["windows_peak_working_set_mib"] = round(
                        counters.peak_working_set / 1024**2, 1
                    )
        else:
            result = check_writes()
        print(json.dumps(result, indent=2))
    except Exception as error:
        # Raw database/provider errors can include credentials. Print only safe messages.
        message = (
            str(error)
            if isinstance(error, (ValueError, RuntimeError))
            else "Konfiguration, Rechte und Dienstverfügbarkeit prüfen"
        )
        print(f"Wartung fehlgeschlagen ({type(error).__name__}): {message}", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
