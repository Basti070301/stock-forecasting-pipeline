from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

try:
    from .config import FEATURE_DIR, MODEL_DIR, REPORT_DIR
    from .feature_engineering import FEATURE_COLUMNS
except ImportError:  # Allows: python src/model_baseline.py
    from config import FEATURE_DIR, MODEL_DIR, REPORT_DIR
    from feature_engineering import FEATURE_COLUMNS


def load_model_data() -> pd.DataFrame:
    feature_file = FEATURE_DIR / "stock_features.csv"
    if not feature_file.exists():
        raise FileNotFoundError(
            f"Feature file not found: {feature_file}. Run feature engineering first."
        )

    frame = pd.read_csv(feature_file, parse_dates=["trade_date"])
    target_map = {"True": 1, "False": 0, True: 1, False: 0, 1: 1, 0: 0}
    frame["target_next_day_up"] = frame["target_next_day_up"].map(target_map)
    return frame.dropna(subset=[*FEATURE_COLUMNS, "target_next_day_up"]).copy()


def chronological_split(
    frame: pd.DataFrame,
    train_fraction: float = 0.8,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    """Split on a calendar cutoff so no future dates enter model training."""

    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be between 0 and 1.")

    dates = pd.Index(sorted(frame["trade_date"].dropna().unique()))
    if len(dates) < 2:
        raise ValueError("At least two unique trade dates are required.")

    cutoff_index = min(max(int(len(dates) * train_fraction) - 1, 0), len(dates) - 2)
    cutoff = pd.Timestamp(dates[cutoff_index])
    train = frame.loc[frame["trade_date"] <= cutoff].copy()
    test = frame.loc[frame["trade_date"] > cutoff].copy()

    if train.empty or test.empty:
        raise ValueError("Chronological split produced an empty partition.")
    return train, test, cutoff


def build_model() -> Pipeline:
    preprocessing = ColumnTransformer(
        transformers=[
            ("numeric", StandardScaler(), FEATURE_COLUMNS),
            ("ticker", OneHotEncoder(handle_unknown="ignore"), ["ticker"]),
        ]
    )
    return Pipeline(
        steps=[
            ("preprocessing", preprocessing),
            (
                "classifier",
                LogisticRegression(max_iter=2_000, random_state=42),
            ),
        ]
    )


def train_baseline(
    frame: pd.DataFrame | None = None,
    train_fraction: float = 0.8,
    save_artifacts: bool = True,
) -> tuple[Pipeline, dict, pd.DataFrame]:
    """Train and evaluate a transparent logistic-regression baseline."""

    model_data = load_model_data() if frame is None else frame.copy()
    train, test, cutoff = chronological_split(model_data, train_fraction)
    input_columns = [*FEATURE_COLUMNS, "ticker"]

    model = build_model()
    model.fit(train[input_columns], train["target_next_day_up"].astype(int))

    prediction = model.predict(test[input_columns])
    probability = model.predict_proba(test[input_columns])[:, 1]
    target = test["target_next_day_up"].astype(int)
    positive_rate = float(target.mean())

    metrics = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": "LogisticRegression",
        "split": "chronological",
        "cutoff_date": cutoff.date().isoformat(),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "train_start": train["trade_date"].min().date().isoformat(),
        "train_end": train["trade_date"].max().date().isoformat(),
        "test_start": test["trade_date"].min().date().isoformat(),
        "test_end": test["trade_date"].max().date().isoformat(),
        "test_positive_rate": positive_rate,
        "majority_baseline_accuracy": max(positive_rate, 1 - positive_rate),
        "accuracy": float(accuracy_score(target, prediction)),
        "balanced_accuracy": float(balanced_accuracy_score(target, prediction)),
        "precision": float(precision_score(target, prediction, zero_division=0)),
        "recall": float(recall_score(target, prediction, zero_division=0)),
        "f1": float(f1_score(target, prediction, zero_division=0)),
        "roc_auc": float(roc_auc_score(target, probability)),
        "confusion_matrix": confusion_matrix(target, prediction).tolist(),
    }

    predictions = test[["ticker", "trade_date"]].copy()
    predictions["actual"] = target.to_numpy()
    predictions["predicted"] = prediction
    predictions["probability_up"] = probability

    if save_artifacts:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, MODEL_DIR / "logistic_regression.joblib")
        (REPORT_DIR / "model_metrics.json").write_text(
            json.dumps(metrics, indent=2), encoding="utf-8"
        )
        predictions.to_csv(REPORT_DIR / "model_predictions.csv", index=False)

    return model, metrics, predictions


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the baseline classifier")
    parser.add_argument("--train-fraction", type=float, default=0.8)
    args = parser.parse_args()

    _, metrics, _ = train_baseline(train_fraction=args.train_fraction)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
