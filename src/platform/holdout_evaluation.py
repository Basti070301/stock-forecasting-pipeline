"""Frozen-model evaluation; explicitly disclose reuse of previously inspected periods."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .forecast_contract import INPUT_COLUMNS, ForecastError, checked_prices, utc_now
from .market import digest
from .model_artifacts import ArtifactRepository, canonical_hash, code_version, file_hash
from .model_training import TrainingSpec, evaluate_holdout, reference_inputs
from .research import prepare
from .research_forecasts import immutable_documents

REUSE_WARNING = (
    "Retrospektive Out-of-Sample-Auswertung: von Training/Kalibrierung der finalen Modelle "
    "ausgeschlossen, aber Zeitraum bereits in früheren Forschungs-Backtests betrachtet. "
    "Kein nachgewiesen projektweit unangetasteter Holdout; keine unabhängige Modellfreigabe."
)


def calibration_summary(target, probability):
    """Ten disjoint bins including both 0 and 1, with no floating-boundary overlap."""
    bins = []
    indices = np.minimum((np.asarray(probability) * 10).astype(int), 9)
    for i in range(10):
        mask = indices == i
        if mask.any():
            bins.append(
                {
                    "lower": i / 10,
                    "upper": (i + 1) / 10,
                    "count": int(mask.sum()),
                    "predicted": float(probability[mask].mean()),
                    "observed": float(target[mask].mean()),
                }
            )
    return {
        "bins": bins,
        "ece": sum(b["count"] * abs(b["predicted"] - b["observed"]) for b in bins) / len(target),
        "mean_probability": float(probability.mean()),
        "positive_rate": float(target.mean()),
    }


def uncertainty(frame, target, probability, majority):
    # Resample whole dates, keeping correlated stocks together, in five-session blocks.
    daily = (
        pd.DataFrame(
            {
                "date": frame.trade_date.to_numpy(),
                "accuracy": ((probability >= 0.5) == target).astype(float),
                "brier_score": (probability - target) ** 2,
                "accuracy_delta_majority": ((probability >= 0.5) == target).astype(float)
                - (target == majority).astype(float),
            }
        )
        .groupby("date")
        .agg(["sum", "count"])
    )
    count = len(daily)
    rng = np.random.default_rng(42)
    draws = []
    for _ in range(1000):
        starts = rng.integers(0, count, size=(count + 4) // 5)
        indices = ((starts[:, None] + np.arange(5)) % count).ravel()[:count]
        sampled = daily.iloc[indices].sum()
        draws.append(
            [
                float(sampled[k, "sum"] / sampled[k, "count"])
                for k in ("accuracy", "brier_score", "accuracy_delta_majority")
            ]
        )
    bounds = np.quantile(draws, [0.025, 0.975], axis=0)
    return {
        "method": "Paired circular five-session date-block bootstrap; 1000 draws; seed 42",
        "intervals_95": {
            k: bounds[:, i].tolist()
            for i, k in enumerate(("accuracy", "brier_score", "accuracy_delta_majority"))
        },
        "unique_sessions": count,
        "low_sample": count < 100,
        "warning": "Deskriptive Unsicherheit auf fünf festen Titeln/einem Zeitraum; keine Regime-, Selektions- oder Mehrfachtestkorrektur und kein Profitabilitätsnachweis.",
    }


def evaluate_models(
    repository, artifact_ids, prices, instruments, *, acknowledge_reused_period=False
):
    if not acknowledge_reused_period:
        raise ForecastError(
            "holdout_not_pristine",
            "Geplanter Referenz-Holdout wurde bereits betrachtet. Retrospektive Auswertung benötigt ausdrückliche Bestätigung; unabhängige Abnahme bleibt offen.",
        )
    if len(artifact_ids) != 2 or len(set(artifact_ids)) != 2:
        raise ForecastError("model_pair", "Explizit ein LR- und ein RF-Artefakt auswählen")
    loaded = [repository.load(identity, trusted=True) for identity in artifact_ids]
    if {m.metadata.model_id for m in loaded} != {"logistic", "random_forest"}:
        raise ForecastError(
            "model_pair", "Vergleich benötigt Logistic Regression und Random Forest"
        )
    specs = [TrainingSpec.model_validate(m.metadata.training_spec) for m in loaded]
    definitions = [s.model_dump(mode="json", exclude={"model"}) for s in specs]
    if (
        definitions[0] != definitions[1]
        or loaded[0].metadata.input_data_hash != loaded[1].metadata.input_data_hash
    ):
        raise ForecastError(
            "holdout_mismatch",
            "Trainings-, Kalibrierungs-, Holdout- oder Datendefinitionen unterscheiden sich",
        )
    results = []
    for model, spec in zip(loaded, specs, strict=True):
        result = evaluate_holdout(model, prices, instruments)
        prefix = checked_prices(
            prices[prices.ticker.isin(spec.tickers)], instruments, end=spec.holdout_end
        )
        frame = prepare(prefix, instruments)
        frame = frame[
            (frame.trade_date > pd.Timestamp(spec.calibration_end))
            & (frame.label_end <= pd.Timestamp(spec.holdout_end))
        ]
        if digest(frame) != result["holdout_hash"]:
            raise ForecastError("holdout_mismatch", "Holdout-Zeilen stimmen nicht überein")
        target = frame.target_next_day_up.astype(int).to_numpy()
        probability = model._probabilities(frame[INPUT_COLUMNS])
        results.append(
            result
            | {
                "name": model.metadata.model_id,
                "artifact_sha256": file_hash(
                    repository.path(model.metadata.artifact_id) / "model.joblib"
                ),
                "training_period": model.metadata.training_period,
                "calibration_period": model.metadata.calibration_period,
                "calibration_summary": calibration_summary(target, probability),
                "uncertainty": uncertainty(
                    frame, target, probability, int(model.metadata.training_positive_rate >= 0.5)
                ),
                "per_ticker_rows": {
                    str(t): int(n) for t, n in frame.groupby("ticker").size().items()
                },
            }
        )
    if results[0]["holdout_hash"] != results[1]["holdout_hash"]:
        raise ForecastError(
            "holdout_mismatch", "Modelle wurden auf unterschiedlichen Holdout-Zeilen geprüft"
        )
    content = {
        "schema_version": 1,
        "kind": "frozen_holdout_comparison",
        "evaluation_code_version": file_hash(__file__),
        "training_code_version": code_version(),
        "definition": definitions[0],
        "evaluation_scope": "retrospective_diagnostic",
        "independent_acceptance": "blocked",
        "warning": REUSE_WARNING,
        "status": "research_only",
        "forecast_enabled": False,
        "results": results,
        "model_selection": "Keine Modellwahl oder Optimierung aus dieser Auswertung",
    }
    fingerprint = canonical_hash(content)
    return content | {
        "id": "eval-" + fingerprint,
        "input_fingerprint": fingerprint,
        "evaluated_at": utc_now().isoformat(),
    }


def save_evaluation(store, report):
    return immutable_documents(store, [("backtests", report["id"], report)])["backtests"]


def main():
    parser = argparse.ArgumentParser(
        description="Expliziter eingefrorener Modellvergleich, ohne Training"
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--artifacts", nargs=2, required=True)
    parser.add_argument("--trust-local-artifacts", action="store_true", required=True)
    parser.add_argument("--acknowledge-reused-period", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args()
    try:
        repository = ArtifactRepository(args.root)
        meta = repository.metadata(args.artifacts[0])
        prices, instruments, _ = reference_inputs(list(meta.instruments))
        report = evaluate_models(
            repository,
            args.artifacts,
            prices,
            instruments,
            acknowledge_reused_period=args.acknowledge_reused_period,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        if args.persist:
            from .config import Settings
            from .store import Store

            store = Store(Settings())
            try:
                if store.settings.mode == "demo":
                    store.migrate()
                save_evaluation(store, report)
            finally:
                store.engine.dispose()
        print(json.dumps({"evaluation_id": report["id"], "scope": report["evaluation_scope"]}))
        return 0
    except (ForecastError, OSError, ValueError):
        print(
            "Auswertung abgelehnt. Freigabe des retrospektiven Zeitraums, Artefakte und neue Ausgabedatei prüfen."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
