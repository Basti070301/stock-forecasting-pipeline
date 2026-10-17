"""M4 research-only artifacts; local reference bars and explicitly synthetic time fixtures."""

import json
import shutil
from datetime import datetime, timezone

import exchange_calendars as xcals
import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression

from src.platform.config import DEFAULT_INSTRUMENTS
from src.platform.forecast_contract import (
    FeatureSnapshot,
    ForecastError,
    SourceProvenance,
    checked_prices,
    latest_available_session,
    prepare_snapshot,
)
from src.platform.market import demo_prices
from src.platform.model_artifacts import ArtifactRepository, file_hash
from src.platform.model_training import (
    TrainingSpec,
    evaluate_holdout,
    final_training,
    training_partitions,
)

INSTRUMENT = DEFAULT_INSTRUMENTS[0].model_dump()
INSTRUMENTS = {"AAPL": INSTRUMENT}
CAL = xcals.get_calendar(INSTRUMENT["calendar"])
NOW = datetime(2026, 10, 17, 15, tzinfo=timezone.utc)


def decision(frame):
    return (
        CAL.session_close(pd.Timestamp(frame.trade_date.max())) + pd.Timedelta(minutes=60)
    ).to_pydatetime()


@pytest.fixture(scope="module")
def inputs():
    prices = demo_prices("AAPL").head(420).copy()
    spec = TrainingSpec(
        tickers=["AAPL"],
        train_end=pd.Timestamp(prices.iloc[220].trade_date).date(),
        calibration_end=pd.Timestamp(prices.iloc[310].trade_date).date(),
        holdout_end=pd.Timestamp(prices.iloc[-1].trade_date).date(),
    )
    source = SourceProvenance(
        name="Reference subset for offline tests; not a live market feed",
        kind="historical_snapshot",
        observed_at=decision(prices.head(311)),
    )
    return prices, spec, source


@pytest.fixture(scope="module")
def trained(inputs, tmp_path_factory):
    prices, spec, source = inputs
    repo = ArtifactRepository(tmp_path_factory.mktemp("final-artifacts"))
    metadata = final_training(prices, INSTRUMENTS, source, spec, repo, clock=lambda: NOW)
    return repo, metadata


def snapshot(inputs, **kwargs):
    prices, _, source = inputs
    return prepare_snapshot(
        prices,
        INSTRUMENT,
        source,
        mode="historical_replay",
        decision_at=decision(prices),
        clock=lambda: NOW,
        **kwargs,
    )


@pytest.mark.parametrize(
    "calendar,at,expected",
    [
        ("XNYS", "2026-07-04T21:00:00Z", "2026-07-02"),
        ("XETR", "2026-07-04T21:00:00Z", "2026-07-03"),
        ("XETR", "2026-04-06T21:00:00Z", "2026-04-02"),
        ("XNYS", "2026-04-06T21:00:00Z", "2026-04-06"),
        ("XNYS", "2026-11-27T18:10:00Z", "2026-11-25"),
        ("XNYS", "2026-11-27T18:16:00Z", "2026-11-27"),
    ],
)
def test_trading_calendar_weekends_holidays_and_early_close(calendar, at, expected):
    assert latest_available_session(calendar, at).date().isoformat() == expected


def test_target_is_next_exchange_session_and_never_a_calendar_day(inputs):
    prepared = snapshot(inputs)
    assert prepared.target_session == CAL.next_session(pd.Timestamp(prepared.feature_as_of)).date()
    assert prepared.data_available_at <= prepared.decision_at <= prepared.prepared_at
    assert prepared.mode == prepared.data_status == "historical_replay"
    invalid = prepared.model_dump() | {"target_session": prepared.feature_as_of}
    with pytest.raises(ValueError, match="nächste gültige"):
        FeatureSnapshot.model_validate(invalid)


def test_october_current_forecast_rejects_august_reference():
    prices = demo_prices("NVDA")
    instrument = DEFAULT_INSTRUMENTS[2].model_dump()
    source = SourceProvenance(
        name="Repository August snapshot",
        kind="historical_snapshot",
        observed_at="2026-08-25T21:30:28Z",
    )
    with pytest.raises(ForecastError, match="Veraltete Kurse") as error:
        prepare_snapshot(prices, instrument, source, clock=lambda: NOW)
    assert error.value.code == "stale_data"


def test_current_mode_cannot_disguise_historical_or_backdated_input(inputs):
    prices, _, source = inputs
    with pytest.raises(ValueError, match="Replay-Modus"):
        prepare_snapshot(
            prices, INSTRUMENT, source, decision_at=decision(prices), clock=lambda: decision(prices)
        )
    current_source = source.model_copy(update={"kind": "stored_market_data"})
    with pytest.raises(ValueError, match="Rückdatierte"):
        prepare_snapshot(
            prices, INSTRUMENT, current_source, decision_at=decision(prices), clock=lambda: NOW
        )


def test_availability_utc_and_future_observation(inputs):
    prices, _, source = inputs
    with pytest.raises(ForecastError, match="Zeitzone"):
        prepare_snapshot(
            prices,
            INSTRUMENT,
            source,
            mode="historical_replay",
            decision_at="2023-01-01",
            clock=lambda: NOW,
        )
    source = source.model_copy(update={"observed_at": NOW})
    with pytest.raises(ValueError, match="Zukunft"):
        prepare_snapshot(
            prices,
            INSTRUMENT,
            source,
            mode="historical_replay",
            decision_at=decision(prices),
            clock=lambda: NOW,
        )
    assert (
        SourceProvenance(
            name="offset fixture",
            kind="stored_market_data",
            observed_at="2026-01-01T10:00:00+02:00",
        ).observed_at.hour
        == 8
    )


@pytest.mark.parametrize("failure", ["empty", "nan", "duplicate", "gap", "invalid_ohlc"])
def test_incomplete_or_invalid_prices_are_rejected(inputs, failure):
    prices = inputs[0].copy()
    if failure == "empty":
        prices = prices.iloc[:0]
    elif failure == "nan":
        prices.loc[prices.index[-1], "close_price"] = np.nan
    elif failure == "duplicate":
        prices = pd.concat([prices, prices.tail(1)])
    elif failure == "gap":
        prices = prices.drop(prices.index[100])
    else:
        prices.loc[prices.index[-1], "low_price"] = 999999
    with pytest.raises(ForecastError):
        checked_prices(prices, INSTRUMENTS)


def test_missing_features_and_schema_rejected(inputs):
    prices, _, source = inputs
    with pytest.raises(ForecastError, match="Features"):
        prepare_snapshot(
            prices.head(20),
            INSTRUMENT,
            source.model_copy(update={"observed_at": decision(prices.head(20))}),
            mode="historical_replay",
            decision_at=decision(prices.head(20)),
            clock=lambda: NOW,
        )
    prepared = snapshot(inputs)
    for features in [
        {},
        prepared.features | {"momentum_7": np.nan},
        prepared.features | {"momentum_7": "0.1"},
    ]:
        with pytest.raises(ValueError, match="Features"):
            FeatureSnapshot.model_validate(prepared.model_dump() | {"features": features})


def test_final_training_boundaries_and_calibration_do_not_touch_holdout(
    inputs, trained, monkeypatch, tmp_path
):
    prices, spec, source = inputs
    _, train, calibration = training_partitions(prices, INSTRUMENTS, spec)
    assert train.label_end.max() < calibration.trade_date.min()
    assert calibration.label_end.max().date() <= spec.calibration_end
    calls = []
    original_fit = LogisticRegression.fit

    def spy(self, x, y, *args, **kwargs):
        calls.append((len(x), np.asarray(y)))
        return original_fit(self, x, y, *args, **kwargs)

    monkeypatch.setattr(LogisticRegression, "fit", spy)
    altered = prices.copy()
    altered.loc[
        pd.to_datetime(altered.trade_date) > pd.Timestamp(spec.calibration_end),
        ["open_price", "high_price", "low_price", "close_price"],
    ] *= 4
    repo2 = ArtifactRepository(tmp_path / "repeat")
    repeated = final_training(altered, INSTRUMENTS, source, spec, repo2, clock=lambda: NOW)
    repo, first = trained
    assert [count for count, _ in calls] == [len(train), len(calibration)]
    np.testing.assert_array_equal(
        calls[1][1], calibration.target_next_day_up.astype(int).to_numpy()
    )
    assert repeated.model_version == first.model_version
    a = repo.load(first.artifact_id, trusted=True).predict_research(
        snapshot(inputs), clock=lambda: NOW
    )
    b = repo2.load(repeated.artifact_id, trusted=True).predict_research(
        snapshot(inputs), clock=lambda: NOW
    )
    assert a.probability == b.probability


@pytest.mark.parametrize("model", ["logistic", "random_forest"])
def test_both_final_estimators_roundtrip_and_research_only(inputs, tmp_path, model):
    prices, spec, source = inputs
    spec = spec.model_copy(update={"model": model})
    repo = ArtifactRepository(tmp_path / model)
    meta = final_training(prices, INSTRUMENTS, source, spec, repo, clock=lambda: NOW)
    first = repo.load(
        meta.artifact_id, trusted=True, expected_version=meta.model_version
    ).predict_research(snapshot(inputs), clock=lambda: NOW)
    second = repo.load(meta.artifact_id, trusted=True).predict_research(
        snapshot(inputs), clock=lambda: NOW
    )
    assert first == second
    assert first.status == meta.status == "research_only"
    assert first.forecast_enabled is False and meta.forecast_enabled is False
    assert first.counterfactual_model_replay is True
    assert 0 <= first.probability <= 1
    assert len(first.artifact_sha256) == 64
    assert {"sklearn", "python", "joblib", "pandas", "numpy", "scipy", "exchange_calendars"} == set(
        meta.library_versions
    )
    assert meta.artifact_kind == "final_research"
    repeated_repo = ArtifactRepository(tmp_path / (model + "-repeat"))
    repeated_meta = final_training(
        prices, INSTRUMENTS, source, spec, repeated_repo, clock=lambda: NOW
    )
    repeated = repeated_repo.load(repeated_meta.artifact_id, trusted=True).predict_research(
        snapshot(inputs), clock=lambda: NOW
    )
    assert repeated_meta.model_version == meta.model_version
    assert first.probability == repeated.probability


def test_repeated_save_is_idempotent_and_does_not_overwrite(inputs, trained):
    repo, meta = trained
    path = repo.path(meta.artifact_id) / "metadata.json"
    before = path.read_bytes()
    repeated = final_training(inputs[0], INSTRUMENTS, inputs[2], inputs[1], repo, clock=lambda: NOW)
    assert meta == repeated and path.read_bytes() == before


@pytest.mark.parametrize(
    "identity",
    [
        "../outside",
        "fold-000.joblib",
        "https://example.com/model",
        "m4-logistic-" + "a" * 24 + "/../",
    ],
)
def test_arbitrary_paths_and_fold_models_refused(trained, identity):
    repo, _ = trained
    with pytest.raises(ForecastError) as error:
        repo.load(identity, trusted=True)
    assert error.value.code == "artifact_id"


def test_unregistered_fold_and_missing_trust_never_deserialize(trained, monkeypatch):
    repo, meta = trained
    monkeypatch.setattr(
        "src.platform.model_artifacts.joblib.load",
        lambda *a, **kw: pytest.fail("Unsafe deserialization"),
    )
    with pytest.raises(ForecastError, match="trusted=True"):
        repo.load(meta.artifact_id)
    with pytest.raises(ForecastError, match="Fold-Artefakte"):
        repo.load("m4-logistic-" + "b" * 24, trusted=True)


def test_corruption_detected_before_loading(trained, tmp_path, monkeypatch):
    original, meta = trained
    shutil.copytree(original.root, tmp_path / "copy")
    repo = ArtifactRepository(tmp_path / "copy")
    path = repo.path(meta.artifact_id) / "model.joblib"
    path.write_bytes(path.read_bytes() + b"corruption")
    monkeypatch.setattr(
        "src.platform.model_artifacts.joblib.load",
        lambda *a, **kw: pytest.fail("Corrupt model loaded"),
    )
    with pytest.raises(ForecastError, match="SHA256"):
        repo.load(meta.artifact_id, trusted=True)


@pytest.mark.parametrize(
    "field,value",
    [
        ("feature_version", "other"),
        ("feature_schema", {}),
        ("library_versions", {}),
        ("code_version", "other"),
        ("artifact_kind", "fold"),
        ("status", "approved"),
        ("forecast_enabled", True),
    ],
)
def test_incompatible_metadata_refused_before_deserialization(
    trained, tmp_path, monkeypatch, field, value
):
    original, meta = trained
    shutil.copytree(original.root, tmp_path / "copy")
    repo = ArtifactRepository(tmp_path / "copy")
    path = repo.path(meta.artifact_id) / "metadata.json"
    payload = json.loads(path.read_text()) | {field: value}
    path.write_text(json.dumps(payload))
    index = json.loads((repo.root / "registry.json").read_text())
    index["artifacts"][meta.artifact_id]["metadata_sha256"] = file_hash(path)
    (repo.root / "registry.json").write_text(json.dumps(index))
    monkeypatch.setattr(
        "src.platform.model_artifacts.joblib.load",
        lambda *a, **kw: pytest.fail("Incompatible model loaded"),
    )
    with pytest.raises(ForecastError):
        repo.load(meta.artifact_id, trusted=True)


def test_wrong_requested_model_version_refused(trained):
    repo, meta = trained
    with pytest.raises(ForecastError, match="Modellversion"):
        repo.load(meta.artifact_id, trusted=True, expected_version="0" * 64)


def test_incompatible_serialized_classifier_refused(trained, tmp_path):
    original, meta = trained
    shutil.copytree(original.root, tmp_path / "copy")
    repo = ArtifactRepository(tmp_path / "copy")
    path = repo.path(meta.artifact_id) / "model.joblib"
    bundle = joblib.load(path)  # Only our own test-generated model, never an external file.
    bundle["model"].steps[-1] = ("classifier", DummyClassifier().fit([[0], [1]], [0, 1]))
    joblib.dump(bundle, path, compress=3)
    index = json.loads((repo.root / "registry.json").read_text())
    index["artifacts"][meta.artifact_id]["model_sha256"] = file_hash(path)
    (repo.root / "registry.json").write_text(json.dumps(index))
    with pytest.raises(ForecastError, match="Estimator"):
        repo.load(meta.artifact_id, trusted=True)


def test_model_not_eligible_before_knowledge_cutoff_or_during_training(inputs, trained):
    repo, meta = trained
    loaded = repo.load(meta.artifact_id, trusted=True)
    early_prices = inputs[0].head(250)
    early_source = inputs[2].model_copy(update={"observed_at": decision(early_prices)})
    early = prepare_snapshot(
        early_prices,
        INSTRUMENT,
        early_source,
        mode="historical_replay",
        decision_at=decision(early_prices),
        clock=lambda: NOW,
    )
    with pytest.raises(ForecastError, match="noch nicht verfügbar"):
        loaded.predict_research(early, clock=lambda: NOW)


def test_holdout_evaluation_does_not_fit_or_promote(inputs, trained, monkeypatch):
    repo, meta = trained
    loaded = repo.load(meta.artifact_id, trusted=True)

    def no_refit(*args, **kwargs):
        pytest.fail("Holdout attempted fit")

    monkeypatch.setattr(LogisticRegression, "fit", no_refit)
    report = evaluate_holdout(loaded, inputs[0], INSTRUMENTS)
    assert report["status"] == "research_only" and not report["forecast_enabled"]
    assert {"roc_auc", "balanced_accuracy", "precision", "recall", "brier_score"}.issubset(
        report["metrics"]
    )
    assert report["calibration"] and report["training_prevalence_baseline"]
    assert meta == repo.metadata(meta.artifact_id)


def test_holdout_cannot_substitute_training_prices(inputs, trained):
    repo, meta = trained
    prices = inputs[0].copy()
    prices.loc[prices.index[10], "volume"] += 1
    with pytest.raises(ForecastError, match="Trainingsdatenstand"):
        evaluate_holdout(repo.load(meta.artifact_id, trusted=True), prices, INSTRUMENTS)


def test_observation_and_training_must_be_available(inputs, tmp_path):
    prices, spec, source = inputs
    with pytest.raises(ForecastError, match="Abrufzeitpunkt"):
        final_training(
            prices,
            INSTRUMENTS,
            source.model_copy(update={"observed_at": decision(prices.head(100))}),
            spec,
            ArtifactRepository(tmp_path),
            clock=lambda: NOW,
        )
    with pytest.raises(ForecastError, match="noch nicht vollständig"):
        final_training(
            prices,
            INSTRUMENTS,
            source,
            spec,
            ArtifactRepository(tmp_path),
            clock=lambda: datetime(2021, 1, 1, tzinfo=timezone.utc),
        )


def test_invalid_training_boundaries(inputs):
    spec = inputs[1].model_dump()
    with pytest.raises(ValueError, match="Training <"):
        TrainingSpec.model_validate(spec | {"train_end": spec["calibration_end"]})
    with pytest.raises(ValueError, match="Doppelte"):
        TrainingSpec.model_validate(spec | {"tickers": ["AAPL", "AAPL"]})


def test_future_prices_cannot_change_snapshot_features(inputs):
    prices, _, source = inputs
    at = decision(prices.head(380))
    original = prepare_snapshot(
        prices, INSTRUMENT, source, mode="historical_replay", decision_at=at, clock=lambda: NOW
    )
    future = prices.copy()
    future.loc[future.index[380:], ["open_price", "high_price", "low_price", "close_price"]] *= 3
    repeated = prepare_snapshot(
        future, INSTRUMENT, source, mode="historical_replay", decision_at=at, clock=lambda: NOW
    )
    assert repeated.features == original.features and repeated.data_version == original.data_version


def test_current_internal_validation_with_explicit_synthetic_clock(inputs, tmp_path):
    prices, spec, source = inputs
    # Clock/source are explicit test fixtures, never published as current financial data.
    train_clock = source.observed_at
    repo = ArtifactRepository(tmp_path)
    meta = final_training(prices, INSTRUMENTS, source, spec, repo, clock=lambda: train_clock)
    current_clock = decision(prices)
    current_source = SourceProvenance(
        name="Synthetic clock fixture, not a live provider",
        kind="stored_market_data",
        observed_at=current_clock,
    )
    current = prepare_snapshot(prices, INSTRUMENT, current_source, clock=lambda: current_clock)
    result = repo.load(meta.artifact_id, trusted=True).predict_research(
        current, clock=lambda: current_clock
    )
    assert result.data_status == "current" and result.counterfactual_model_replay is False
    assert result.forecast_enabled is False
    with pytest.raises(ForecastError, match="zeitlich nicht zulässig"):
        repo.load(meta.artifact_id, trusted=True).predict_research(
            current, clock=lambda: current_clock + pd.Timedelta(minutes=6)
        )


def test_requested_universe_cannot_hide_an_untrained_stock(inputs, tmp_path):
    prices, spec, source = inputs
    short = prices.tail(20).copy()
    short["ticker"] = "MSFT"
    instruments = INSTRUMENTS | {"MSFT": DEFAULT_INSTRUMENTS[1].model_dump()}
    with pytest.raises(ForecastError, match="Kursdaten fehlen"):
        final_training(
            pd.concat([prices, short]),
            instruments,
            source,
            spec.model_copy(update={"tickers": ["AAPL", "MSFT"]}),
            ArtifactRepository(tmp_path),
            clock=lambda: NOW,
        )
