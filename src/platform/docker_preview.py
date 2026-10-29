"""Explicit historical test maintenance. Never an API job or a current-data source."""

import json
import shutil
from pathlib import Path

from sqlalchemy import inspect, select, text
from sqlalchemy.dialects.postgresql import insert

from src.config import PROJECT_ROOT

from .forecast_contract import ForecastError
from .holdout_evaluation import save_evaluation
from .market_data_store import MarketRepository
from .model_artifacts import ArtifactRepository, canonical_hash, file_hash
from .model_training import TrainingSpec, final_training, reference_inputs
from .research_forecasts import ForecastRequest, ResearchForecastEngine
from .store import TABLES, Store, utcnow


def require_preview(settings):
    if (
        not settings.historical_preview
        or settings.allow_mutations
        or settings.news_auto_refresh
        or settings.current_auto_refresh
        or settings.current_enabled
        or settings.market_enabled
    ):
        raise ValueError(
            "Explizites historisches Leseprofil mit deaktivierten Providern/Schedulern erforderlich"
        )
    root = (settings.research_artifact_dir or settings.runtime_dir / "preview-models").resolve()
    if not root.is_relative_to(settings.runtime_dir.resolve()):
        raise ValueError(
            "Preview-Artefakte müssen im eigenen persistenten Runtime-Verzeichnis liegen"
        )
    return root


def seed_reference_files(raw=None):
    source = Path(raw or PROJECT_ROOT / "reference/raw")
    copied = 0
    for folder, suffix in (("prices", "csv"), ("profiles", "json")):
        for ticker in ("AAPL", "MSFT", "NVDA", "SAP_DE", "ALV_DE"):
            relative = Path(folder) / f"{ticker}_20260825T213028Z.{suffix}"
            original, target = source / relative, PROJECT_ROOT / "data/raw" / relative
            if target.is_symlink() or (
                target.exists() and file_hash(target) != file_hash(original)
            ):
                raise ValueError("Vorhandene Referenzdatei weicht ab; kein Überschreiben")
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original, target)
                copied += 1
    return copied


def prepare_research(settings):
    root = require_preview(settings)
    repository = ArtifactRepository(root)
    manifest = root / "preview-artifacts.json"
    if manifest.exists():
        entries = json.loads(manifest.read_text())["models"]
        if len(entries) != 2 or {row["name"] for row in entries} != {"logistic", "random_forest"}:
            raise ValueError("Preview-Manifest ungültig")
        for row in entries:
            repository.metadata(row["artifact_id"], expected_version=row["model_version"])
        return {"models": entries, "reused": True, "scope": "historical_preview"}
    prices, instruments, source = reference_inputs(["AAPL", "MSFT", "NVDA", "SAP.DE", "ALV.DE"])
    models = []
    for name in ("logistic", "random_forest"):
        spec = TrainingSpec(
            model=name,
            tickers=list(instruments),
            train_end="2025-12-31",
            calibration_end="2026-03-31",
            holdout_end="2026-08-25",
        )
        metadata = final_training(prices, instruments, source, spec, repository)
        models.append(
            {
                "name": name,
                "artifact_id": metadata.artifact_id,
                "model_version": metadata.model_version,
            }
        )
    result = {"models": models, "scope": "historical_preview", "research_only": True}
    # Exclusive manifest creation; the original registry/model files are never replaced here.
    with manifest.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
    return result | {"reused": False}


def replay_research(settings, engine):
    root = require_preview(settings)
    entries = json.loads((root / "preview-artifacts.json").read_text())["models"]
    store = Store(settings, engine=engine)
    research = ResearchForecastEngine(store, ArtifactRepository(root))
    results = []
    for model in entries:
        for ticker in ("AAPL", "MSFT", "NVDA", "SAP.DE", "ALV.DE"):
            request = ForecastRequest(
                artifact_id=model["artifact_id"],
                model_version=model["model_version"],
                ticker=ticker,
                mode="historical_replay",
                decision_at="2026-08-25T21:45:00Z",
            )
            result = research.run(request)
            row = store.get("forecasts", result["forecast_id"])
            if (
                row["mode"] != "historical_replay"
                or row["status"] != "research_only"
                or row["forecast_enabled"]
                or not row["counterfactual_model_replay"]
            ):
                raise ForecastError("preview_contract", "Historischer Replay-Vertrag verletzt")
            results.append({"ticker": ticker, "model": model["name"], **result})
    return {"historical_replays": results, "current_forecasts_created": 0}


def seed_reports(settings, engine):
    require_preview(settings)
    path = PROJECT_ROOT / "reports/research/m4_1_retrospective_diagnostic_v1.json"
    if file_hash(path) != "6f06c82b7724a74265e21fbada3c6a4ade7a8c8da4e69dbb4e638cbb62e721b9":
        raise ValueError(
            "Historischer Diagnosebericht weicht von seiner eingefrorenen Prüfsumme ab"
        )
    report = json.loads(path.read_text())
    if report.get("evaluation_scope") != "retrospective_diagnostic":
        raise ValueError("Nur unveränderter historischer Diagnosebericht erlaubt")
    saved = save_evaluation(Store(settings, engine=engine), report)
    return {
        "report_id": saved["id"],
        "scope": report["evaluation_scope"],
        "source_sha256": file_hash(path),
    }


def verify_preview(settings, engine):
    require_preview(settings)
    required = [
        "dim_stock",
        "fact_stock_price",
        "fact_stock_features",
        "si_news",
        "si_forecasts",
        "si_outcomes",
        "si_market_observations",
        "si_price_revisions",
        "si_market_runs",
    ]
    known = set(inspect(engine).get_table_names())
    if not set(required).issubset(known):
        raise ValueError("Preview-Schema unvollständig")
    with engine.connect() as conn:
        counts = {
            name: conn.execute(
                text(
                    f'SELECT COUNT(*) FROM "{name}"'
                    + (" WHERE mode='live'" if name.startswith("si_") else "")
                )
            ).scalar_one()
            for name in required
        }
        versions = (
            conn.execute(text("SELECT version FROM si_deployment_migrations ORDER BY version"))
            .scalars()
            .all()
        )
        reader = conn.execute(
            text(
                "SELECT has_table_privilege('si_reader', 'si_market_observations', 'SELECT') AND NOT has_table_privilege('si_reader','si_forecasts','INSERT')"
            )
        ).scalar_one()
    store = Store(settings, engine=engine)
    if not MarketRepository(store).migrated():
        raise ValueError("Marktdatenmigration v4 fehlt")
    if not reader or len(versions) != 4 or not store.get("schema_versions", "v4"):
        raise ValueError("Migrationen oder Leserollenrechte unvollständig")
    if (
        any(f.get("mode") == "current" for f in store.all("forecasts"))
        or store.all("provider_calls")
        or store.all("market_observations")
    ):
        raise ValueError("Unerwartete Current-Daten/Provideraktivität im historischen Teststack")
    fingerprint = canonical_hash(
        {name: store.all(name) for name in ("forecasts", "outcomes", "backtests", "models")}
    )
    # Storage-only fixtures, in a namespace never selected by the live/demo API.
    # No financial outcome/price or fake observed market value is generated.
    with engine.begin() as conn:
        for name in ("news", "forecasts", "outcomes", "market_observations", "price_revisions"):
            table = TABLES[name]
            identity = "preview:storage-roundtrip-v1"
            payload = {"kind": "storage_fixture", "table": name, "not_market_data": True}
            conn.execute(
                insert(table)
                .values(id=identity, mode="preview", created_at=utcnow(), payload=payload)
                .on_conflict_do_nothing()
            )
            if (
                conn.execute(select(table.c.payload).where(table.c.id == identity)).scalar_one()
                != payload
            ):
                raise ValueError("Isolierte Speicherprobe verändert; Abbruch")
    return {
        "counts": counts,
        "deployment_migrations": versions,
        "reader_select_only": bool(reader),
        "research_fingerprint": fingerprint,
        "provider_calls": 0,
        "current_forecasts": 0,
        "storage_fixture_namespace": "preview (not market data)",
    }
