"""M4.1 offline tests; reference subsets are fixtures, never a fresh holdout claim."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sqlalchemy import select

from src.platform.api import create_app
from src.platform.config import DEFAULT_INSTRUMENTS, Settings
from src.platform.forecast_contract import ForecastError, SourceProvenance
from src.platform.holdout_evaluation import calibration_summary, evaluate_models, save_evaluation
from src.platform.market import demo_prices
from src.platform.model_artifacts import ArtifactRepository, file_hash
from src.platform.model_training import TrainingSpec, final_training
from src.platform.research_forecasts import (
    ForecastRequest,
    ResearchForecastEngine,
    immutable_documents,
    record_outcome,
)
from src.platform.store import TABLES, Store

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
INSTRUMENTS = {"AAPL": DEFAULT_INSTRUMENTS[0].model_dump()}
CAL = xcals.get_calendar("XNYS")


def after_close(prices):
    return (
        CAL.session_close(pd.Timestamp(prices.trade_date.max())) + pd.Timedelta(hours=1)
    ).to_pydatetime()


@pytest.fixture(scope="module")
def frozen_pair(tmp_path_factory):
    prices = demo_prices("AAPL").head(420).copy()
    spec = TrainingSpec(
        tickers=["AAPL"],
        train_end=pd.Timestamp(prices.iloc[220].trade_date).date(),
        calibration_end=pd.Timestamp(prices.iloc[310].trade_date).date(),
        holdout_end=pd.Timestamp(prices.iloc[-1].trade_date).date(),
    )
    source = SourceProvenance(
        name="Offline reference test subset, not live",
        kind="historical_snapshot",
        observed_at=after_close(prices.head(311)),
    )
    repo = ArtifactRepository(tmp_path_factory.mktemp("m41-fixture-artifacts"))
    models = [
        final_training(
            prices,
            INSTRUMENTS,
            source,
            spec.model_copy(update={"model": model}),
            repo,
            clock=lambda: NOW,
        )
        for model in ("logistic", "random_forest")
    ]
    return prices, source, repo, models


@pytest.fixture
def store(tmp_path, frozen_pair):
    store = Store(
        Settings(
            _env_file=None,
            runtime_dir=tmp_path,
            mode="demo",
            news_auto_refresh=False,
            research_artifact_dir=frozen_pair[2].root,
            research_trust_local_artifacts=True,
        )
    )
    store.migrate()
    yield store
    store.engine.dispose()


def engine_for(store, frozen_pair, prices=None):
    frame, source, repo, _ = frozen_pair
    return ResearchForecastEngine(
        store,
        repo,
        clock=lambda: NOW,
        inputs=lambda request: (frame if prices is None else prices, INSTRUMENTS, source),
    )


def request_for(frozen_pair, **overrides):
    prices, _, _, models = frozen_pair
    return ForecastRequest(
        artifact_id=models[0].artifact_id,
        model_version=models[0].model_version,
        ticker="AAPL",
        mode="historical_replay",
        decision_at=after_close(prices),
        **overrides,
    )


def test_replay_persists_complete_contract_idempotently_across_restart(store, frozen_pair):
    engine = engine_for(store, frozen_pair)
    request = request_for(frozen_pair)
    first = engine.run(request)
    record = store.get("forecasts", first["forecast_id"])
    assert record["counterfactual_model_replay"] and record["mode"] == "historical_replay"
    assert record["status"] == "research_only" and not record["forecast_enabled"]
    assert record["model_version"] == request.model_version and len(record["features"]) == 6
    assert 0 <= record["probability"] <= 1
    assert record["decision_at"] != record["generated_at"]
    assert (
        record["target_session"]
        == CAL.next_session(pd.Timestamp(record["feature_as_of"])).date().isoformat()
    )
    store.engine.dispose()
    restarted = Store(store.settings)
    try:
        result = engine_for(restarted, frozen_pair).run(request)
        assert result == {"forecast_id": first["forecast_id"], "reused": True}
        assert restarted.get("forecasts", first["forecast_id"]) == record
        assert len(restarted.all("forecasts")) == len(restarted.all("models")) == 1
    finally:
        restarted.engine.dispose()


def test_changed_input_conflicts_without_overwriting(store, frozen_pair):
    engine = engine_for(store, frozen_pair)
    request = request_for(frozen_pair)
    result = engine.run(request)
    original = store.get("forecasts", result["forecast_id"])
    modified = frozen_pair[0].copy()
    modified.loc[0, "volume"] += (
        1  # Historical prefix hash, even if final rolling feature unchanged.
    )
    with pytest.raises(ForecastError, match="Abweichende Eingaben"):
        engine_for(store, frozen_pair, modified).run(request)
    assert store.get("forecasts", result["forecast_id"]) == original


def test_atomic_conflict_rolls_back_model_document(store):
    immutable_documents(
        store, [("forecasts", "fixed", {"input_fingerprint": "first", "probability": 0.2})]
    )
    with pytest.raises(ForecastError):
        immutable_documents(
            store,
            [
                ("models", "rollback", {"input_fingerprint": "new"}),
                ("forecasts", "fixed", {"input_fingerprint": "changed", "probability": 0.9}),
            ],
        )
    assert store.get("models", "rollback") is None
    assert store.get("forecasts", "fixed")["probability"] == 0.2


def test_concurrent_inserts_are_atomic_and_immutable(store):
    def write(i):
        try:
            return immutable_documents(
                store,
                [("forecasts", "concurrent", {"input_fingerprint": str(i), "probability": i / 10})],
            )
        except ForecastError:
            return None

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(write, range(5)))
    assert sum(result is not None for result in results) == 1
    assert len(store.all("forecasts")) == 1


def test_cross_process_database_lease_no_parallel_inference(store, frozen_pair, monkeypatch):
    engine = engine_for(store, frozen_pair)
    second_store = Store(store.settings)
    other = engine_for(second_store, frozen_pair)
    request = request_for(frozen_pair)
    owner = engine.claim(request.identity())
    monkeypatch.setattr(
        other, "prepare", lambda request: pytest.fail("Parallel request reached preparation")
    )
    try:
        with pytest.raises(ForecastError) as error:
            other.run(request)
        assert error.value.code == "job_busy"
        engine.release(request.identity(), "incorrect-owner")
        with pytest.raises(ForecastError):
            other.claim(request.identity())
    finally:
        engine.release(request.identity(), owner)
        second_store.engine.dispose()
    assert store.all("news_locks") == []


def test_rejection_releases_lease_and_preserves_store(store, frozen_pair):
    request = request_for(frozen_pair).model_copy(update={"model_version": "0" * 64})
    with pytest.raises(ForecastError):
        engine_for(store, frozen_pair).run(request)
    assert store.all("news_locks") == store.all("forecasts") == []


def test_trust_and_stale_current_data_are_rejected(store, frozen_pair):
    engine = engine_for(store, frozen_pair)
    store.settings.research_trust_local_artifacts = False
    with pytest.raises(ForecastError) as error:
        engine.run(request_for(frozen_pair))
    assert error.value.code == "trust_required"
    store.settings.research_trust_local_artifacts = True
    current = request_for(frozen_pair).model_copy(update={"mode": "current", "decision_at": NOW})
    with pytest.raises(ForecastError) as error:
        engine.run(current)
    assert error.value.code == "stale_data"


def test_future_bars_do_not_change_replay_features(store, frozen_pair):
    prices = frozen_pair[0]
    short = prices.head(419)
    request = request_for(frozen_pair).model_copy(update={"decision_at": after_close(short)})
    original = engine_for(store, frozen_pair).prepare(request)
    altered = prices.copy()
    altered.loc[altered.index[-1], ["open_price", "high_price", "low_price", "close_price"]] *= 10
    new = engine_for(store, frozen_pair, altered).prepare(request)
    assert original[1].features == new[1].features and original[2] == new[2]


@pytest.mark.parametrize(
    "changes",
    [
        {"artifact_id": "../../model.joblib"},
        {"model_version": "invalid"},
        {"ticker": "UNKNOWN"},
        {"decision_at": "2026-08-25"},
        {"mode": "live"},
        {"model_path": "C:/untrusted.joblib"},
    ],
)
def test_request_schema_rejects_paths_missing_zone_and_unknown_inputs(frozen_pair, changes):
    with pytest.raises(ValueError):
        ForecastRequest.model_validate(request_for(frozen_pair).model_dump() | changes)


def test_frozen_comparison_never_fits_and_uses_same_rows_and_baselines(
    store, frozen_pair, monkeypatch
):
    prices, _, repo, models = frozen_pair
    hashes = {m.artifact_id: file_hash(repo.path(m.artifact_id) / "model.joblib") for m in models}

    def forbidden(*args, **kwargs):
        pytest.fail("Evaluation must not fit or recalibrate")

    monkeypatch.setattr(LogisticRegression, "fit", forbidden)
    monkeypatch.setattr(RandomForestClassifier, "fit", forbidden)
    report = evaluate_models(
        repo, list(hashes), prices, INSTRUMENTS, acknowledge_reused_period=True
    )
    assert report["independent_acceptance"] == "blocked" and not report["forecast_enabled"]
    a, b = report["results"]
    assert a["holdout_hash"] == b["holdout_hash"]
    assert a["training_majority_baseline"] == b["training_majority_baseline"]
    assert a["holdout_period"]["rows"] == sum(a["per_ticker_rows"].values())
    for result in report["results"]:
        assert (
            sum(b["count"] for b in result["calibration_summary"]["bins"])
            == result["holdout_period"]["rows"]
        )
        assert result["uncertainty"]["unique_sessions"] > 0
        assert 0 <= result["calibration_summary"]["ece"] <= 1
        assert result["status"] == "research_only"
    assert hashes == {
        m.artifact_id: file_hash(repo.path(m.artifact_id) / "model.joblib") for m in models
    }
    stored = save_evaluation(store, report)
    assert save_evaluation(store, report)["id"] == stored["id"]
    assert len(store.all("backtests")) == 1


def test_holdout_reuse_requires_explicit_acknowledgment(frozen_pair):
    prices, _, repo, models = frozen_pair
    with pytest.raises(ForecastError) as error:
        evaluate_models(repo, [m.artifact_id for m in models], prices, INSTRUMENTS)
    assert error.value.code == "holdout_not_pristine"


def test_calibration_bins_include_zero_one_and_exact_boundaries():
    result = calibration_summary(np.array([0, 1, 0, 1]), np.array([0.0, 0.3, 0.7, 1.0]))
    assert sum(b["count"] for b in result["bins"]) == 4
    assert len(result["bins"]) == 4
    assert result["ece"] == pytest.approx(0.35)


def test_comparison_rejects_mismatched_date_definition(frozen_pair, monkeypatch):
    prices, _, repo, models = frozen_pair
    loaded = [repo.load(m.artifact_id, trusted=True) for m in models]
    spec = dict(loaded[1].metadata.training_spec)
    spec["holdout_end"] = (
        (pd.Timestamp(spec["holdout_end"]) + pd.Timedelta(days=1)).date().isoformat()
    )
    loaded[1].metadata = loaded[1].metadata.model_copy(update={"training_spec": spec})
    lookup = {m.metadata.artifact_id: m for m in loaded}
    monkeypatch.setattr(repo, "load", lambda identity, **kwargs: lookup[identity])
    with pytest.raises(ForecastError) as error:
        evaluate_models(repo, list(lookup), prices, INSTRUMENTS, acknowledge_reused_period=True)
    assert error.value.code == "holdout_mismatch"


def test_current_contract_with_controlled_historical_clock_and_observation_fixture(
    store, frozen_pair, tmp_path
):
    prices, source, _, models = frozen_pair
    # Controlled historical clock, not evidence of current live prices.
    repo = ArtifactRepository(tmp_path / "current-fixture")
    spec = TrainingSpec.model_validate(models[0].training_spec)
    meta = final_training(prices, INSTRUMENTS, source, spec, repo, clock=lambda: source.observed_at)
    now = after_close(prices)
    observed = SourceProvenance(
        name="Controlled stored-price observation fixture",
        kind="stored_market_data",
        observed_at=now,
    )
    engine = ResearchForecastEngine(
        store, repo, clock=lambda: now, inputs=lambda request: (prices, INSTRUMENTS, observed)
    )
    request = ForecastRequest(
        artifact_id=meta.artifact_id,
        model_version=meta.model_version,
        ticker="AAPL",
        mode="current",
        decision_at=now,
    )
    record = store.get("forecasts", engine.run(request)["forecast_id"])
    assert record["mode"] == "current" and not record["counterfactual_model_replay"]


def test_outcome_waits_for_target_and_observation_and_preserves_forecast(store, frozen_pair):
    prices = frozen_pair[0]
    request = request_for(frozen_pair).model_copy(
        update={"decision_at": after_close(prices.head(419))}
    )
    identity = engine_for(store, frozen_pair).run(request)["forecast_id"]
    original = store.get("forecasts", identity)
    source = SourceProvenance(
        name="Reference target bar", kind="historical_snapshot", observed_at=after_close(prices)
    )
    with pytest.raises(ForecastError) as error:
        record_outcome(store, identity, prices, source, clock=lambda: request.decision_at)
    assert error.value.code == "outcome_not_available"
    outcome = record_outcome(store, identity, prices, source, clock=lambda: NOW)
    assert outcome["actual"] == int(prices.iloc[-1].close_price > prices.iloc[-2].close_price)
    assert record_outcome(store, identity, prices, source, clock=lambda: NOW)["id"] == outcome["id"]
    assert store.get("forecasts", identity) == original
    revised = prices.copy()
    revised.loc[0, "volume"] += 1
    with pytest.raises(ForecastError, match="Datenstand"):
        record_outcome(store, identity, revised, source, clock=lambda: NOW)


def test_api_job_access_control_and_persistent_forecast(store, frozen_pair, monkeypatch):
    prices, source, _, _ = frozen_pair
    monkeypatch.setattr(
        "src.platform.research_forecasts.reference_inputs",
        lambda tickers: (prices, INSTRUMENTS, source),
    )
    store.settings.mutation_token = "local-test-token"
    body = request_for(frozen_pair).model_dump(mode="json")
    with TestClient(create_app(store.settings, store)) as client:
        catalog = client.get("/api/research/models").json()
        assert len(catalog["items"]) == 2 and catalog["can_generate"]
        assert client.post("/api/forecasts/research", json=body).status_code == 403
        headers = {"X-SI-Token": "local-test-token"}
        assert (
            client.post(
                "/api/forecasts/research",
                headers=headers | {"Origin": "https://evil.invalid"},
                json=body,
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/forecasts/research", headers=headers, json=body | {"artifact_id": "../../bad"}
            ).status_code
            == 422
        )
        response = client.post("/api/forecasts/research", headers=headers, json=body)
        assert response.status_code == 202
        for _ in range(200):
            job = client.get("/api/jobs/" + response.json()["job_id"]).json()
            if job["status"] in {"failed", "succeeded"}:
                break
            time.sleep(0.01)
        assert job["status"] == "succeeded", job
        items = client.get("/api/forecasts?ticker=AAPL").json()["items"]
        assert len(items) == 1 and items[0]["kind"] == "research_forecast"
        assert items[0]["counterfactual_model_replay"]
        assert client.get("/api/forecasts?ticker=MSFT").json()["items"] == []
        assert client.get("/api/forecasts?limit=0").status_code == 422
        assert client.get("/api/research/evaluations").json()["items"] == []
        assert "local-test-token" not in json.dumps(catalog)
    with TestClient(create_app(store.settings, store)) as client:
        assert len(client.get("/api/forecasts?ticker=AAPL").json()["items"]) == 1


def test_docker_read_profile_blocks_research_generation(store, frozen_pair):
    store.settings.allow_mutations = False
    with TestClient(create_app(store.settings, store)) as client:
        assert (
            client.post(
                "/api/forecasts/research", json=request_for(frozen_pair).model_dump(mode="json")
            ).status_code
            == 403
        )
        assert not client.get("/api/research/models").json()["can_generate"]


def test_api_hides_future_outcome(store):
    store.add("forecasts", {"ticker": "AAPL", "probability": 0.5}, "test-future")
    store.add(
        "outcomes",
        {"forecast_id": "test-future", "actual": 1, "outcome_at": "2099-01-01T21:00:00Z"},
        "test-future",
    )
    with TestClient(create_app(store.settings, store)) as client:
        assert client.get("/api/forecasts").json()["items"][0]["outcome"] is None


def test_postgresql_statement_shape_only_not_runtime():
    from sqlalchemy.dialects.postgresql import dialect, insert

    statement = (
        insert(TABLES["forecasts"])
        .values(id="demo:test", mode="demo", created_at="test", payload={})
        .on_conflict_do_nothing()
    )
    assert "ON CONFLICT DO NOTHING" in str(statement.compile(dialect=dialect()))
    # Deliberately no PostgreSQL connection; runtime acceptance stays BLOCKED.
    assert select(TABLES["forecasts"]).compile(dialect=dialect()) is not None


def test_prepared_artifact_fingerprint_is_rechecked_before_persistence(store, frozen_pair):
    engine = engine_for(store, frozen_pair)
    request = request_for(frozen_pair)
    meta, snapshot, _ = engine.prepare(request)
    with pytest.raises(ForecastError) as error:
        engine.run_prepared(request, (meta, snapshot, "changed-after-prepare"))
    assert error.value.code == "artifact_changed"
    assert store.all("forecasts") == store.all("models") == []


def test_api_reports_temporal_validation_failure_without_internal_error(
    store, frozen_pair, monkeypatch
):
    prices, source, _, _ = frozen_pair
    monkeypatch.setattr(
        "src.platform.research_forecasts.reference_inputs",
        lambda tickers: (prices, INSTRUMENTS, source),
    )
    body = request_for(frozen_pair).model_dump(mode="json")
    body["decision_at"] = after_close(
        prices.head(250)
    ).isoformat()  # Before actual snapshot observation.
    with TestClient(create_app(store.settings, store)) as client:
        response = client.post("/api/forecasts/research", json=body)
        assert response.status_code == 409
        assert response.json()["code"] == "invalid_snapshot"
        assert "Traceback" not in response.text
    assert store.all("forecasts") == store.all("news_locks") == []


def test_unreadable_registry_has_safe_configuration_error(store, frozen_pair, tmp_path):
    folder = tmp_path / "invalid-registry"
    folder.mkdir()
    (folder / "registry.json").write_text("{broken")
    engine = ResearchForecastEngine(store, ArtifactRepository(folder))
    with pytest.raises(ForecastError) as error:
        engine.prepare(request_for(frozen_pair))
    assert error.value.code == "invalid_metadata"
    assert str(folder) not in str(error.value)
