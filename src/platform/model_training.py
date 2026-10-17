"""Fixed-cutoff final research training on existing features/estimators. No network or DB writes."""

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

import exchange_calendars as xcals
import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sklearn.linear_model import LogisticRegression

from src.config import PROJECT_ROOT

from .config import DEFAULT_INSTRUMENTS, Settings
from .forecast_contract import (
    FEATURE_SCHEMA,
    INPUT_COLUMNS,
    ForecastError,
    SourceProvenance,
    checked_prices,
    latest_available_session,
    prepare_snapshot,
    utc,
    utc_now,
)
from .market import SNAPSHOT, demo_prices, digest
from .model_artifacts import (
    ARTIFACT_FORMAT,
    ArtifactMetadata,
    ArtifactRepository,
    canonical_hash,
    code_version,
    file_hash,
    runtime_versions,
)
from .research import calibration_bins, logit, metrics, prepare, research_estimator


class TrainingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    model: Literal["logistic", "random_forest"] = "logistic"
    tickers: list[str] = Field(min_length=1, max_length=20)
    train_end: date
    calibration_end: date
    holdout_end: date
    seed: Literal[42] = 42
    publication_delay_seconds: int = Field(default=900, ge=0, le=86400)

    @model_validator(mode="after")
    def ordered(self):
        if not self.train_end < self.calibration_end < self.holdout_end:
            raise ForecastError(
                "split_boundaries", "Training < Kalibrierung < Holdout-Ende erforderlich"
            )
        if len(set(self.tickers)) != len(self.tickers):
            raise ForecastError("duplicate_ticker", "Doppelte Aktien im Trainingsuniversum")
        return self


def training_partitions(prices, instruments, spec):
    if not set(spec.tickers).issubset(instruments):
        raise ForecastError("unknown_instrument", "Bestätigte Instrumentstammdaten fehlen")
    if "ticker" not in prices:
        raise ForecastError("missing_prices", "Aktienzuordnung der Kursdaten fehlt")
    # Crop BEFORE feature/label construction. Independent holdout rows never enter fitting.
    selected = prices[prices.ticker.isin(spec.tickers)]
    prefix = checked_prices(selected, instruments, end=spec.calibration_end)
    if set(prefix.ticker) != set(spec.tickers):
        raise ForecastError("missing_prices", "Kursdaten fehlen für mindestens eine Trainingsaktie")
    frame = prepare(prefix, instruments)
    train = frame[frame.label_end <= pd.Timestamp(spec.train_end)].copy()
    calibration = frame[
        (frame.trade_date > pd.Timestamp(spec.train_end))
        & (frame.label_end <= pd.Timestamp(spec.calibration_end))
    ].copy()
    if train.trade_date.nunique() < 120 or calibration.trade_date.nunique() < 30:
        raise ForecastError(
            "short_training", "Mindestens 120 Trainings- und 30 Kalibrierungssitzungen erforderlich"
        )
    if any(
        train.loc[train.ticker == ticker, "trade_date"].nunique() < 120
        or calibration.loc[calibration.ticker == ticker, "trade_date"].nunique() < 30
        for ticker in spec.tickers
    ):
        raise ForecastError(
            "short_training",
            "Jede Trainingsaktie benötigt 120 Trainings- und 30 Kalibrierungssitzungen",
        )
    if train.target_next_day_up.nunique() < 2 or calibration.target_next_day_up.nunique() < 2:
        raise ForecastError("single_class", "Training und Kalibrierung benötigen beide Zielklassen")
    if train.label_end.max() >= calibration.trade_date.min():
        raise ForecastError("temporal_leak", "Trainingslabels überlappen den Kalibrierungszeitraum")
    return prefix, train, calibration


def period(frame):
    return {
        "start": frame.trade_date.min().date().isoformat(),
        "end": frame.trade_date.max().date().isoformat(),
        "last_label_session": frame.label_end.max().date().isoformat(),
        "rows": len(frame),
        "unique_sessions": int(frame.trade_date.nunique()),
    }


def final_training(prices, instruments, source, spec, repository, *, clock=utc_now):
    created = utc(clock())
    prefix, train, calibration = training_partitions(prices, instruments, spec)
    knowledge = utc(source.observed_at)
    for ticker, group in prefix.groupby("ticker"):
        if group.trade_date.max() > latest_available_session(
            instruments[ticker]["calendar"], source.observed_at, spec.publication_delay_seconds
        ):
            raise ForecastError(
                "unavailable_training",
                "Kursdaten waren zum deklarierten Abrufzeitpunkt nicht vollständig verfügbar",
            )
    for ticker, group in calibration.groupby("ticker"):
        cal = xcals.get_calendar(instruments[ticker]["calendar"])
        known_label = cal.session_close(group.label_end.max()) + pd.Timedelta(
            seconds=spec.publication_delay_seconds
        )
        knowledge = max(knowledge, known_label)
    if knowledge > created:
        raise ForecastError(
            "future_training", "Trainings-/Kalibrierungsdaten sind noch nicht vollständig verfügbar"
        )
    model = research_estimator(spec.model)
    model.fit(train[INPUT_COLUMNS], train.target_next_day_up.astype(int))
    calibrator = LogisticRegression(random_state=spec.seed)
    calibrator.fit(
        logit(model.predict_proba(calibration[INPUT_COLUMNS])[:, 1]),
        calibration.target_next_day_up.astype(int),
    )
    versions = runtime_versions()
    inputs_hash = digest(prefix)
    train_hash = digest(train)
    cal_hash = digest(calibration)
    selected_instruments = {ticker: instruments[ticker] for ticker in sorted(spec.tickers)}
    identity_basis = {
        "format": ARTIFACT_FORMAT,
        "spec": spec.model_dump(mode="json"),
        "input_hash": inputs_hash,
        "training_hash": train_hash,
        "calibration_hash": cal_hash,
        "instruments": selected_instruments,
        "code_version": code_version(),
        "versions": versions,
        "feature_schema": FEATURE_SCHEMA,
        "source_name": source.name,
        "source_kind": source.kind,
        "source_observed_at": utc(source.observed_at).isoformat(),
    }
    version = canonical_hash(identity_basis)
    identity = f"m4-{spec.model}-{version[:24]}"
    metadata = ArtifactMetadata(
        artifact_id=identity,
        model_id=spec.model,
        model_version=version,
        created_at=created.to_pydatetime(),
        knowledge_available_at=knowledge.to_pydatetime(),
        feature_schema=FEATURE_SCHEMA,
        input_columns=INPUT_COLUMNS,
        code_version=identity_basis["code_version"],
        library_versions=versions,
        source=source,
        input_data_hash=inputs_hash,
        training_data_hash=train_hash,
        calibration_data_hash=cal_hash,
        training_spec=spec.model_dump(mode="json"),
        training_period=period(train),
        calibration_period=period(calibration),
        instruments=selected_instruments,
        hyperparameters=model.named_steps["classifier"].get_params(),
        calibration_hyperparameters=calibrator.get_params(),
        training_positive_rate=float(train.target_next_day_up.astype(int).mean()),
        evaluation_plan={
            "status": "not_evaluated",
            "holdout_feature_start_exclusive": spec.calibration_end.isoformat(),
            "holdout_label_end_inclusive": spec.holdout_end.isoformat(),
            "metrics": [
                "accuracy",
                "balanced_accuracy",
                "precision",
                "recall",
                "f1",
                "roc_auc",
                "brier_score",
                "calibration_bins",
            ],
            "baselines": ["training_prevalence", "training_majority", "logistic", "random_forest"],
            "walk_forward": "Separate bestehende research.evaluate-Ergebnisse; keine automatische Übernahme oder Freigabe",
        },
        limitations=[
            "research_only; keine Modellfreigabe oder operativen Forecasts",
            "Close-to-Close-Richtung ist keine Open-to-Close-Handelsrendite",
            "Historische adjustierte Snapshots sind kein point-in-time Corporate-Action-/Survivorship-Nachweis",
            "Holdout wurde nicht zur Optimierung oder Kalibrierung verwendet",
            "Replay eines später erzeugten Modells ist ausdrücklich eine kontrafaktische Forschungssimulation",
        ],
    )
    bundle = {
        "artifact_format": ARTIFACT_FORMAT,
        "artifact_id": identity,
        "model_version": version,
        "model": model,
        "calibrator": calibrator,
        "input_columns": INPUT_COLUMNS,
    }
    return repository.save(metadata, bundle)


def evaluate_holdout(loaded, prices, instruments):
    """Explicit later evaluation only. Never fit/refit, mutate a model, or promote it."""
    spec = TrainingSpec.model_validate(loaded.metadata.training_spec)
    prefix = checked_prices(
        prices[prices.ticker.isin(spec.tickers)], instruments, end=spec.holdout_end
    )
    # Ensure a later caller cannot substitute a different training history for this model.
    if (
        digest(
            prefix[prefix.trade_date <= pd.Timestamp(spec.calibration_end)].reset_index(drop=True)
        )
        != loaded.metadata.input_data_hash
    ):
        raise ForecastError(
            "data_version", "Holdout-Datensatz verändert den registrierten Trainingsdatenstand"
        )
    frame = prepare(prefix, instruments)
    holdout = frame[
        (frame.trade_date > pd.Timestamp(spec.calibration_end))
        & (frame.label_end <= pd.Timestamp(spec.holdout_end))
    ]
    if holdout.empty:
        raise ForecastError("missing_holdout", "Keine unabhängigen Holdout-Zeilen vorhanden")
    probability = loaded._probabilities(holdout[INPUT_COLUMNS])
    target = holdout.target_next_day_up.astype(int).to_numpy()
    prior = loaded.metadata.training_positive_rate
    return {
        "artifact_id": loaded.metadata.artifact_id,
        "model_version": loaded.metadata.model_version,
        "holdout_hash": digest(holdout),
        "holdout_period": period(holdout),
        "status": "research_only",
        "forecast_enabled": False,
        "metrics": metrics(target, probability),
        "training_prevalence_baseline": metrics(target, np.full(len(target), prior)),
        "training_majority_baseline": metrics(target, np.full(len(target), float(prior >= 0.5))),
        "calibration": calibration_bins(target, probability),
        "walk_forward": "Unabhängig im bestehenden Research-Modul auswerten; kein automatischer Modellvergleich/-Promoting",
    }


def reference_inputs(tickers):
    instruments = {
        item.ticker: item.model_dump() for item in DEFAULT_INSTRUMENTS if item.ticker in tickers
    }
    if set(instruments) != set(tickers):
        raise ForecastError(
            "unknown_instrument", "CLI unterstützt nur die fünf bestätigten Repository-Aktien"
        )
    prices = pd.concat([demo_prices(ticker) for ticker in tickers], ignore_index=True)
    hashes = {}
    for ticker in tickers:
        path = PROJECT_ROOT / "data/raw/prices" / f"{ticker.replace('.', '_')}_{SNAPSHOT}.csv"
        hashes[str(path.relative_to(PROJECT_ROOT))] = file_hash(path)
    source = SourceProvenance(
        name="Yahoo Finance / versionierter Repository-Snapshot",
        kind="historical_snapshot",
        observed_at=datetime.strptime(SNAPSHOT, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc),
        snapshot_hashes=hashes,
    )
    return prices, instruments, source


def main():
    parser = argparse.ArgumentParser(
        description="M4.0: finale lokale Forschungsartefakte, keine operativen Forecasts"
    )
    parser.add_argument("command", choices=["train", "inspect", "smoke", "evaluate-holdout"])
    parser.add_argument("--root", type=Path)
    parser.add_argument("--model", choices=["logistic", "random_forest"], default="logistic")
    parser.add_argument(
        "--tickers", nargs="+", default=["AAPL", "MSFT", "NVDA", "SAP.DE", "ALV.DE"]
    )
    parser.add_argument("--train-end", type=date.fromisoformat)
    parser.add_argument("--calibration-end", type=date.fromisoformat)
    parser.add_argument("--holdout-end", type=date.fromisoformat)
    parser.add_argument("--artifact-id")
    parser.add_argument("--ticker", default="AAPL")
    parser.add_argument("--as-of")
    parser.add_argument("--historical-replay", action="store_true")
    parser.add_argument("--trust-local-artifacts", action="store_true")
    args = parser.parse_args()
    try:
        repository = ArtifactRepository(args.root or Settings().runtime_dir / "research-models")
        if args.command == "train":
            if not all([args.train_end, args.calibration_end, args.holdout_end]):
                raise ForecastError(
                    "missing_cutoff", "Alle drei expliziten Datumsgrenzen sind erforderlich"
                )
            spec = TrainingSpec(
                model=args.model,
                tickers=args.tickers,
                train_end=args.train_end,
                calibration_end=args.calibration_end,
                holdout_end=args.holdout_end,
            )
            prices, instruments, source = reference_inputs(args.tickers)
            metadata = final_training(prices, instruments, source, spec, repository)
            result = {
                "artifact_id": metadata.artifact_id,
                "model_version": metadata.model_version,
                "status": metadata.status,
                "forecast_enabled": False,
                "root": str(repository.root),
            }
        elif args.command == "inspect":
            if not args.artifact_id:
                raise ForecastError("missing_id", "Artefakt-ID erforderlich")
            result = repository.metadata(args.artifact_id).model_dump(mode="json")
        else:
            if not args.artifact_id:
                raise ForecastError("missing_id", "Artefakt-ID erforderlich")
            loaded = repository.load(args.artifact_id, trusted=args.trust_local_artifacts)
            prices, instruments, source = reference_inputs(list(loaded.metadata.instruments))
            if args.command == "evaluate-holdout":
                result = evaluate_holdout(loaded, prices, instruments)
            else:
                if bool(args.as_of) != args.historical_replay:
                    raise ForecastError(
                        "replay_required",
                        "--as-of verlangt ausdrücklich --historical-replay und umgekehrt",
                    )
                if args.ticker not in instruments:
                    raise ForecastError("unknown_instrument", "Aktie gehört nicht zum Modell")
                snapshot = prepare_snapshot(
                    prices,
                    instruments[args.ticker],
                    source,
                    mode="historical_replay" if args.historical_replay else "current",
                    decision_at=args.as_of,
                )
                result = loaded.predict_research(snapshot).model_dump(mode="json")
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except ForecastError as error:
        print(json.dumps({"code": error.code, "error": str(error)}, ensure_ascii=False))
        return 1
    except (ValueError, OSError, KeyError, AttributeError, TypeError):
        print(
            json.dumps(
                {"error": "Lokale Eingaben, Modellmetadaten oder Artefaktdateien sind ungültig"}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
