"""Controlled fixtures/virtual clocks only; never evidence of live provider acceptance."""

import copy
import json
import shutil
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from src.platform.api import create_app
from src.platform.config import Settings
from src.platform.current_cli import main
from src.platform.current_forecasts import PROTOCOL_PATH, CurrentForecastPipeline
from src.platform.current_scheduler import CurrentScheduler
from src.platform.forecast_contract import ForecastError, utc
from src.platform.jobs import Jobs
from src.platform.market_data_provider import MarketReceipt, encode_frame
from src.platform.model_artifacts import ArtifactRepository, file_hash
from src.platform.prospective import current_status, prospective_summary
from src.platform.store import Store
from tests.test_research_forecasts import frozen_pair as frozen_pair  # re-export existing fixture


class Clock:
    def __init__(self, value="2026-10-26T21:00:00+00:00"):
        self.value = datetime.fromisoformat(value)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


def bars(end="2026-10-26", ticker="AAPL"):
    days = xcals.get_calendar("XNYS").sessions_in_range("2025-10-27", end)
    prices = 100 + np.arange(len(days)) * 0.02 + np.sin(np.arange(len(days)) * 0.2) * 0.3
    return pd.DataFrame(
        {
            "Open": prices,
            "High": prices + 1,
            "Low": prices - 1,
            "Close": prices + 0.1,
            "Volume": 1000 + np.arange(len(days)),
            "Dividends": 0.0,
            "Stock Splits": 0.0,
        },
        index=days.tz_localize("America/New_York"),
    )


def observe(pipeline, prices=None, **overrides):
    prices = bars() if prices is None else prices
    clock = pipeline.clock
    fields = {
        "ticker": "AAPL",
        "requested_start": prices.index[0].date(),
        "requested_end": prices.index[-1].date(),
        "request_started_at": clock() - timedelta(seconds=2),
        "received_at": clock() - timedelta(seconds=1),
        "source_kind": "fixture",
        "library_version": "fixture-v1",
        "declared_delay_seconds": 900,
        "payload": encode_frame(prices),
    }
    receipt = MarketReceipt(**(fields | overrides))
    pipeline.market.persist(receipt)
    return receipt


@pytest.fixture
def pipeline(tmp_path, frozen_pair):
    _, _, repository, models = frozen_pair
    settings = Settings(
        _env_file=None,
        runtime_dir=tmp_path,
        research_artifact_dir=repository.root,
        research_trust_local_artifacts=True,
        current_enabled=True,
        market_delay_seconds=900,
    )
    store = Store(settings)
    store.migrate()
    clock = Clock()
    protocol = json.loads(PROTOCOL_PATH.read_text())
    protocol["universe"] = ["AAPL"]
    protocol["models"] = [
        {
            "artifact_id": m.artifact_id,
            "model_version": m.model_version,
            "metadata_sha256": file_hash(repository.path(m.artifact_id) / "metadata.json"),
            "artifact_sha256": file_hash(repository.path(m.artifact_id) / "model.joblib"),
            "training_positive_rate": m.training_positive_rate,
        }
        for m in models
    ]
    result = CurrentForecastPipeline(
        store, clock=clock, repository=repository, fixture_mode=True, test_protocol=protocol
    )
    result.market.migrate()
    observe(result)
    yield result
    store.engine.dispose()


def test_manual_pair_uses_existing_engine_persists_atomic_and_idempotent(pipeline):
    report = pipeline.run()
    assert report["source_kind"] == "fixture" and report["status"] == "completed"
    original = pipeline.store.all("forecasts")
    assert len(original) == 2
    assert {r["model_name"] for r in original} == {"logistic", "random_forest"}
    assert len({r["decision_at"] for r in original}) == 1
    assert len({r["data_version"] for r in original}) == 1
    assert all(
        r["evaluation_scope"] == "fixture"
        and r["status"] == "research_only"
        and not r["forecast_enabled"]
        and not r["counterfactual_model_replay"]
        for r in original
    )
    assert all(len(r["features"]) == 6 and 0 <= r["probability"] <= 1 for r in original)
    assert all(r["target_session"] == "2026-10-27" for r in original)
    pipeline.clock.advance(30)
    assert pipeline.run()["results"][0]["reused"]
    assert pipeline.store.all("forecasts") == original
    pipeline.store.engine.dispose()
    fresh = Store(pipeline.settings)
    restarted = CurrentForecastPipeline(
        fresh,
        clock=pipeline.clock,
        repository=pipeline.engine.repository,
        fixture_mode=True,
        test_protocol=pipeline.protocol,
    )
    try:
        assert restarted.run()["results"][0]["reused"]
        assert fresh.all("forecasts") == original
    finally:
        fresh.engine.dispose()
    assert prospective_summary(pipeline)["T0"] is None


def test_model_partner_failure_saves_neither_forecast(pipeline, monkeypatch):
    build = pipeline.engine.prediction_documents
    calls = []

    def fail_second(request, prepared):
        calls.append(request)
        if len(calls) == 2:
            raise ForecastError("integrity", "Fixture: zweites Artefakt fehlerhaft")
        return build(request, prepared)

    monkeypatch.setattr(pipeline.engine, "prediction_documents", fail_second)
    assert pipeline.run()["status"] == "blocked"
    assert pipeline.store.all("forecasts") == []
    assert pipeline.store.all("models") == []
    assert pipeline.store.get("news_locks", "research:current-pipeline") is None
    monkeypatch.setattr(pipeline.engine, "prediction_documents", build)
    pipeline.clock.advance(20)
    assert pipeline.run()["status"] == "completed"
    assert len(pipeline.store.all("forecasts")) == 2


def test_deadline_rechecked_after_inference_no_late_pair(pipeline, monkeypatch):
    build = pipeline.engine.prediction_documents

    def slow(*args):
        result = build(*args)
        pipeline.clock.advance(200)
        return result

    monkeypatch.setattr(pipeline.engine, "prediction_documents", slow)
    report = pipeline.run()
    assert report["status"] == "blocked"
    assert report["results"][0]["code"] == "late_forecast"
    assert pipeline.store.all("forecasts") == []


def test_commit_confirmation_crash_recovery_never_regenerates(pipeline, monkeypatch):
    original = pipeline.confirm_pair
    monkeypatch.setattr(
        pipeline, "confirm_pair", Mock(side_effect=RuntimeError("simulated process crash"))
    )
    with pytest.raises(RuntimeError):
        pipeline.run()
    before = pipeline.store.all("forecasts")
    assert len(before) == 2
    assert prospective_summary(pipeline)["prospective_pairs"] == 0
    monkeypatch.setattr(pipeline, "confirm_pair", original)
    pipeline.clock.advance(15)
    assert pipeline.run()["results"][0]["reused"]
    assert pipeline.store.all("forecasts") == before


def test_late_confirmation_after_restart_is_excluded(pipeline, monkeypatch):
    original = pipeline.confirm_pair
    monkeypatch.setattr(pipeline, "confirm_pair", Mock(side_effect=RuntimeError("crash")))
    with pytest.raises(RuntimeError):
        pipeline.run()
    monkeypatch.setattr(pipeline, "confirm_pair", original)
    pipeline.clock.advance(301)
    assert pipeline.run()["results"][0]["code"] == "late_forecast"
    assert prospective_summary(pipeline)["prospective_pairs"] == 0
    assert len(pipeline.store.all("forecasts")) == 2


def test_global_lease_prevents_two_api_or_cli_workers(pipeline):
    owner = pipeline.engine.claim("current-pipeline")
    try:
        with pytest.raises(ForecastError) as error:
            pipeline.run()
        assert error.value.code == "job_busy"
        assert not pipeline.store.all("forecasts")
    finally:
        pipeline.engine.release("current-pipeline", owner)


def test_session_retry_budget_persistent_no_unlimited_retries(pipeline, monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "paired_documents",
        Mock(side_effect=ForecastError("missing_prices", "Fixture: Daten fehlen")),
    )
    for _ in range(3):
        assert pipeline.run()["results"][0]["code"] == "missing_prices"
        pipeline.clock.advance(1)
    assert pipeline.run()["results"][0]["code"] == "attempt_budget"
    assert pipeline.paired_documents.call_count == 3


def test_asof_features_never_take_later_revision(pipeline):
    first = pipeline.market.observations("AAPL", pipeline.clock())[-1]
    decision = pipeline.clock()
    pipeline.clock.advance(20)
    revised = bars()
    revised.loc[revised.index[-1], "Close"] += 0.5
    later = observe(pipeline, revised)
    documents, _ = pipeline.paired_documents("AAPL", decision)
    forecasts = [p for name, _, p in documents if name == "forecasts"]
    assert all(f["market_receipt_id"] == first["id"] for f in forecasts)
    assert all(f["market_receipt_id"] != str(later.receipt_id) for f in forecasts)
    pipeline.run()
    assert all(
        f["market_receipt_id"] == str(later.receipt_id) for f in pipeline.store.all("forecasts")
    )


def test_equal_observation_timestamps_never_pick_random_uuid_as_latest_revision(pipeline):
    revised = bars()
    revised.loc[revised.index[-1], "Close"] += 0.5
    observe(pipeline, revised)
    report = pipeline.run()
    assert report["results"][0]["code"] == "ambiguous_observation"
    assert pipeline.store.all("forecasts") == []


@pytest.mark.parametrize("issue", ["stale", "missing", "features", "wrong_source", "unknown_delay"])
def test_bad_inputs_block_current_forecasts(pipeline, issue):
    pipeline.clock.advance(10)
    data = bars()
    overrides = {}
    if issue == "stale":
        data = data.iloc[:-1]
    elif issue == "missing":
        data = data.drop(data.index[-3])
    elif issue == "features":
        data.loc[data.index[-2], "Volume"] = 0
    elif issue == "wrong_source":
        overrides["source_kind"] = (
            "provider"  # Simulated provenance ONLY inside isolated fixture DB.
        )
    else:
        overrides["declared_delay_seconds"] = None
    observe(pipeline, data, **overrides)
    assert pipeline.run()["status"] == "blocked"
    assert not pipeline.store.all("forecasts")


def test_invalid_model_hash_blocks_loading(pipeline):
    pipeline.protocol = copy.deepcopy(pipeline.protocol)
    pipeline.protocol["models"][0]["artifact_sha256"] = "0" * 64
    assert pipeline.run()["results"][0]["code"] == "protocol_model"
    assert pipeline.store.all("forecasts") == []


def test_artifact_corruption_is_rejected_without_touching_original(pipeline, tmp_path):
    target = tmp_path / "untrusted-copy"
    shutil.copytree(pipeline.engine.repository.root, target)
    artifact = pipeline.protocol["models"][0]["artifact_id"]
    path = target / artifact / "model.joblib"
    path.write_bytes(b"fixture corruption")
    pipeline.engine.repository = ArtifactRepository(target)
    assert pipeline.run()["results"][0]["code"] == "integrity"
    assert not pipeline.store.all("forecasts")


def test_target_open_blocks_backfill_and_exchange_windows_differ(pipeline):
    with pytest.raises(ForecastError):
        pipeline.plan("AAPL", "2026-10-26T18:00:00+00:00")
    pipeline.protocol = copy.deepcopy(pipeline.protocol)
    pipeline.protocol["universe"] = ["AAPL", "SAP.DE"]
    assert pipeline.plan("SAP.DE", "2026-10-26T18:00:00+00:00")["session"] == "2026-10-26"
    assert pipeline.plan("AAPL", "2026-10-26T21:00:00+00:00")["session"] == "2026-10-26"
    assert (
        pipeline.plan("SAP.DE", "2026-10-26T21:00:00+00:00")["target_open"]
        != pipeline.plan("AAPL", "2026-10-26T21:00:00+00:00")["target_open"]
    )


def test_outcomes_wait_for_actual_observation_and_survive_restart(pipeline):
    pipeline.run()
    before = pipeline.store.all("forecasts")
    assert pipeline.outcomes() == []
    pipeline.clock.value = datetime(2026, 10, 27, 21, tzinfo=timezone.utc)
    assert all(r["status"] == "blocked" for r in pipeline.outcomes())
    observe(pipeline, bars("2026-10-27"))
    assert {r["status"] for r in pipeline.outcomes()} == {"recorded"}
    original = pipeline.store.all("outcomes")
    assert len(original) == 2
    assert all(
        o["target_session"] == "2026-10-27" and o["market_evidence"]["target_revision_id"]
        for o in original
    )
    assert all(
        utc(o["market_evidence"]["forecast_saved_at"]) < utc(o["observed_at"]) for o in original
    )
    pipeline.clock.advance(10)
    assert {r["status"] for r in pipeline.outcomes()} == {"unchanged"}
    assert pipeline.store.all("forecasts") == before
    pipeline.store.engine.dispose()
    assert pipeline.store.all("outcomes") == original


def test_outcome_correction_is_append_only_and_idempotent(pipeline):
    pipeline.run()
    pipeline.clock.value = datetime(2026, 10, 27, 21, tzinfo=timezone.utc)
    observe(pipeline, bars("2026-10-27"))
    pipeline.outcomes()
    first = pipeline.store.all("outcomes")
    pipeline.clock.advance(10)
    corrected = bars("2026-10-27")
    corrected.loc[corrected.index[-1], "Close"] -= 0.5
    observe(pipeline, corrected)
    assert {r["status"] for r in pipeline.outcomes()} == {"revision_recorded"}
    pipeline.clock.advance(10)
    assert {r["status"] for r in pipeline.outcomes()} == {"revision_recorded"}
    revisions = [
        r for r in pipeline.store.all("market_runs") if r["kind"] == "current_outcome_revision"
    ]
    assert len(revisions) == 2
    assert pipeline.store.all("outcomes") == first


def test_changed_adjustment_basis_blocks_outcome_instead_of_mixing_vintages(pipeline):
    pipeline.run()
    pipeline.clock.value = datetime(2026, 10, 27, 21, tzinfo=timezone.utc)
    revised = bars("2026-10-27")
    revised.loc[revised.index[0], "Dividends"] = (
        0.2  # OHLCV unchanged, action revision must still block.
    )
    observe(pipeline, revised)
    assert {r["code"] for r in pipeline.outcomes()} == {"outcome_revision"}
    assert pipeline.store.all("outcomes") == []


def test_verification_does_not_write_current_forecasts_or_accept_fixtures(pipeline):
    report = pipeline.verify()
    assert report["predictions"] == 2 and report["forecast_rows_created"] == 0
    assert not pipeline.store.all("forecasts")
    with pytest.raises(ForecastError):
        pipeline.accept(report["validation_id"], "fixture-browser-evidence")
    assert prospective_summary(pipeline)["T0"] is None
    assert prospective_summary(pipeline)["status"] == "Insufficient Evidence"


@pytest.mark.parametrize(
    "change,code",
    [
        ({"allow_mutations": False}, "read_only"),
        ({"research_trust_local_artifacts": False}, "trust_required"),
    ],
)
def test_read_profile_and_untrusted_models_block_even_fixture_jobs(pipeline, change, code):
    for key, value in change.items():
        setattr(pipeline.settings, key, value)
    with pytest.raises(ForecastError) as error:
        pipeline.run()
    assert error.value.code == code


def test_real_pipeline_default_blocked_no_network_or_auto_acceptance(pipeline):
    real = CurrentForecastPipeline(pipeline.store, clock=pipeline.clock)
    with pytest.raises(ForecastError) as error:
        real.run()
    assert error.value.code == "provider_blocked"
    assert not pipeline.store.all("forecasts")
    pipeline.settings.market_enabled = True
    pipeline.settings.market_rights_accepted = True
    pipeline.settings.market_rights_reference = "fixture-not-real-permission"
    with pytest.raises(ForecastError) as error:
        real.run()
    assert error.value.code == "acceptance_required"
    assert not [r for r in pipeline.store.all("market_runs") if r["kind"] == "current_acceptance"]


def test_old_unresolved_outcome_does_not_starve_new_market_data_refresh(pipeline, monkeypatch):
    pipeline.fixture_mode = False  # Simulated contract; SDK below is entirely mocked.
    pipeline.store.add(
        "forecasts",
        {
            "protocol_hash": pipeline.protocol_hash,
            "source_kind": "provider",
            "market_first_session": "2020-01-01",
            "ticker": "AAPL",
        },
        "old-unresolved-test-fixture",
    )
    runner = Mock()
    runner.run.return_value = {"status": "success"}
    monkeypatch.setattr("src.platform.current_forecasts.MarketIngestion", Mock(return_value=runner))
    assert pipeline.refresh(["AAPL"]) == [{"status": "success"}]
    assert (pipeline.clock().date() - runner.run.call_args.args[1]).days == 365
    assert pipeline.store.get("forecasts", "old-unresolved-test-fixture") is not None


def test_scheduler_disabled_calendar_aware_and_uses_existing_jobs(pipeline):
    jobs = Mock()
    scheduler = CurrentScheduler(pipeline.store, jobs, factory=lambda store: pipeline)
    scheduler.start()
    assert scheduler.thread is None and not scheduler.tick()
    jobs.submit.assert_not_called()
    pipeline.settings.current_auto_refresh = True
    pipeline.clock.value = datetime(2026, 10, 26, 18, tzinfo=timezone.utc)
    assert not scheduler.tick()
    pipeline.clock.value = datetime(2026, 10, 26, 21, tzinfo=timezone.utc)
    assert scheduler.tick()
    assert jobs.submit.call_args.args[0] == "current-scheduled"
    # The real callback would reject fixture network fetches; execute a separate manual fixture job.
    pipeline.run()
    assert not scheduler.tick()


def test_scheduler_bound_and_read_profile_gate(pipeline):
    pipeline.settings.current_auto_refresh = True
    pipeline.settings.current_max_cycles = 2
    scheduler = CurrentScheduler(pipeline.store, Mock(), factory=lambda store: pipeline)
    scheduler.stop_event = SimpleNamespace(is_set=lambda: False, wait=Mock(return_value=False))
    scheduler.run()
    assert scheduler.cycles == 2 and scheduler.stop_event.wait.call_count == 1
    pipeline.settings.allow_mutations = False
    scheduler.start()
    assert scheduler.thread is None and scheduler.blocked_code == "read_only"


def test_existing_jobs_record_history_and_restart_marks_interrupted(pipeline):
    jobs = Jobs(pipeline.store)
    submitted = jobs.submit("current-fixture", lambda: pipeline.run())
    jobs.close()
    assert pipeline.store.get("jobs", submitted["job_id"])["status"] == "succeeded"
    pipeline.store.add(
        "jobs", {"status": "running", "kind": "current-interrupted"}, "interrupted-fixture"
    )
    restarted = Jobs(pipeline.store)
    try:
        assert pipeline.store.get("jobs", "interrupted-fixture")["status"] == "interrupted"
    finally:
        restarted.close()


def test_current_api_auth_validation_and_docker_read_profile(pipeline):
    pipeline.settings.mutation_token = "fixture-current-token"
    pipeline.settings.current_auto_refresh = False
    with TestClient(create_app(pipeline.settings, pipeline.store)) as client:
        status = client.get("/api/research/current/status").json()
        assert status["blocked"] and status["prospective"]["status"] == "Insufficient Evidence"
        assert not status["scheduler"]["running"]
        assert "fixture-current-token" not in json.dumps(status)
        assert client.post("/api/forecasts/current", json={"tickers": ["AAPL"]}).status_code == 403
        headers = {"X-SI-Token": "fixture-current-token"}
        assert (
            client.post(
                "/api/forecasts/current",
                headers=headers | {"Origin": "https://evil.invalid"},
                json={"tickers": ["AAPL"]},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/forecasts/current",
                headers=headers,
                json={"tickers": ["AAPL"], "decision_at": "2026-01-01"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/forecasts/current", headers=headers, json={"tickers": ["UNKNOWN"]}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/forecasts/current", headers=headers, json={"tickers": ["AAPL"]}
            ).status_code
            == 409
        )
    pipeline.settings.allow_mutations = False
    with TestClient(create_app(pipeline.settings, pipeline.store)) as client:
        assert (
            client.post(
                "/api/forecasts/current", headers=headers, json={"tickers": ["AAPL"]}
            ).status_code
            == 403
        )
        assert client.get("/api/research/current/status").status_code == 200


def test_rejected_current_cycle_is_a_failed_job_not_a_green_success(pipeline, monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "paired_documents",
        Mock(side_effect=ForecastError("missing_prices", "Fixture: Kurse fehlen")),
    )
    jobs = Jobs(pipeline.store)
    submitted = jobs.submit("current-fixture-failure", pipeline.job)
    jobs.close()
    record = pipeline.store.get("jobs", submitted["job_id"])
    assert record["status"] == "failed"
    assert "Kein aktuelles Research-Paar erfolgreich bestätigt" in record["error"]
    assert not pipeline.store.all("forecasts")
    assert current_status(pipeline)["last_cycle"]["status"] == "blocked"


def test_api_controlled_fixture_jobs_and_future_outcomes_hidden(pipeline, monkeypatch):
    monkeypatch.setattr("src.platform.api.CurrentForecastPipeline", lambda store: pipeline)
    monkeypatch.setattr("src.platform.api.utc_now", pipeline.clock)
    with TestClient(create_app(pipeline.settings, pipeline.store)) as client:
        response = client.post("/api/forecasts/current", json={"tickers": ["AAPL"]})
        assert response.status_code == 202
        for _ in range(200):
            job = client.get("/api/jobs/" + response.json()["job_id"]).json()
            if job["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.01)
        assert job["status"] == "succeeded", job
        rows = client.get("/api/forecasts?ticker=AAPL").json()["items"]
        assert len(rows) == 2 and all(f["source_kind"] == "fixture" for f in rows)
        assert all(f["current_confirmation"]["status"] == "fixture" for f in rows)
        pipeline.store.add(
            "outcomes",
            {"forecast_id": rows[0]["id"], "actual": 1, "observed_at": "2099-01-01T00:00:00Z"},
            rows[0]["id"],
        )
        assert all(f["outcome"] is None for f in client.get("/api/forecasts").json()["items"])
        assert (
            client.get("/api/research/current/status").json()["prospective"]["prospective_pairs"]
            == 0
        )


def test_status_and_cli_remain_safe_without_schema_or_provider(tmp_path, monkeypatch, capsys):
    settings = Settings(_env_file=None, runtime_dir=tmp_path)
    store = Store(settings)
    pipeline = CurrentForecastPipeline(store)
    assert current_status(pipeline)["blocked"]["code"] == "trust_required"
    monkeypatch.setattr("src.platform.current_cli.Settings", lambda: settings)
    assert main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["prospective"]["T0"] is None
    assert main(["run", "--tickers", "AAPL"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"
    assert main(["schedule", "--cycles", "1"]) == 1


def simulated_accepted_provider(pipeline):
    """Hypothetical provider metadata inside the disposable test DB ONLY; no HTTP.

    The non-production test protocol hash cannot activate the real frozen cohort.
    This tests the acceptance/read contracts, not actual provider rights.
    """
    pipeline.fixture_mode = False
    pipeline.settings.market_enabled = True
    pipeline.settings.market_rights_accepted = True
    pipeline.settings.market_rights_reference = "SIMULATED-TEST-PERMISSION-NOT-A-REAL-ACCEPTANCE"
    pipeline.clock.advance(3)
    observe(pipeline, source_kind="provider")
    validation = pipeline.verify()
    assert validation["forecast_rows_created"] == 0
    acceptance = pipeline.accept(validation["validation_id"], "SIMULATED-API-BROWSER-EVIDENCE")
    pipeline.settings.current_acceptance_id = acceptance["acceptance_id"]
    return validation, acceptance


def test_acceptance_is_explicit_evidence_bound_and_never_auto_enables_scheduler(pipeline):
    validation, acceptance = simulated_accepted_provider(pipeline)
    assert not acceptance["automatic_activation"]
    assert not pipeline.settings.current_auto_refresh
    pipeline.clock.advance(1)
    assert (
        pipeline.accept(validation["validation_id"], "SIMULATED-API-BROWSER-EVIDENCE") == acceptance
    )
    pipeline.settings.market_rights_reference = "changed-simulated-access"
    with pytest.raises(ForecastError) as error:
        pipeline.gate()
    assert error.value.code == "acceptance_required"
    pipeline.settings.market_rights_reference = "SIMULATED-TEST-PERMISSION-NOT-A-REAL-ACCEPTANCE"
    pipeline.settings.market_delay_seconds = 1800
    with pytest.raises(ForecastError):
        pipeline.gate()


def test_simulated_future_cohort_metrics_baselines_and_missing_session_coverage(pipeline):
    simulated_accepted_provider(pipeline)
    result = pipeline.run()
    assert result["status"] == "completed"
    report = prospective_summary(pipeline)
    assert report["prospective_pairs"] == 1 and report["matured_pairs"] == 0
    assert report["T0"] is not None and all(m["n"] == 0 for m in report["models"])
    assert report["status"] == "Insufficient Evidence"
    pipeline.clock.value = datetime(2026, 10, 27, 21, tzinfo=timezone.utc)
    observe(pipeline, bars("2026-10-27"), source_kind="provider")
    pipeline.outcomes()
    report = prospective_summary(pipeline)
    assert report["matured_pairs"] == 1
    for model in report["models"]:
        assert model["n"] == 1
        assert model["metrics"]["roc_auc"] is None
        assert 0 <= model["metrics"]["brier_score"] <= 1
        assert model["training_prevalence_baseline"]["brier_score"] is not None
        assert model["per_ticker"]["AAPL"]["n"] == 1
    assert not report["primary_analysis_executed"]
    pipeline.clock.value = datetime(2026, 11, 5, 21, tzinfo=timezone.utc)
    later = prospective_summary(pipeline)
    assert later["instruments"]["AAPL"]["eligible_sessions"] > 1
    assert later["instruments"]["AAPL"]["coverage"] < 1


def test_hypothetical_cohort_hides_future_outcomes_and_replays(pipeline):
    simulated_accepted_provider(pipeline)
    pipeline.run()
    pipeline.clock.value = datetime(2026, 10, 27, 21, tzinfo=timezone.utc)
    observe(pipeline, bars("2026-10-27"), source_kind="provider")
    pipeline.outcomes()
    cutoff = datetime(2026, 10, 27, 20, tzinfo=timezone.utc)
    assert prospective_summary(pipeline, cutoff)["matured_pairs"] == 0
    for row in pipeline.store.all("forecasts"):
        pipeline.store.add(
            "forecasts",
            {**row, "mode": "historical_replay", "counterfactual_model_replay": True},
            "replay-fixture:" + row["id"],
        )
    assert prospective_summary(pipeline)["prospective_pairs"] == 1


def test_missing_or_late_acceptance_never_admits_hypothetical_pair(pipeline):
    _, acceptance = simulated_accepted_provider(pipeline)
    pipeline.run()
    row = pipeline.store.get("market_runs", acceptance["acceptance_id"])
    assert row["operator_attestation"]
    assert (
        prospective_summary(pipeline, pipeline.clock() - timedelta(seconds=1))["prospective_pairs"]
        == 0
    )
