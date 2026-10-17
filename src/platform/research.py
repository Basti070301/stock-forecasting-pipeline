"""Purged walk-forward research; never promotes a model into production."""

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Literal

import exchange_calendars as xcals
import joblib
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, model_validator
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline

from src.feature_engineering import FEATURE_COLUMNS, calculate_features
from src.model_baseline import build_model

from .market import digest, records


class BacktestRequest(BaseModel):
    model: Literal["logistic", "random_forest"] = "logistic"
    tickers: list[str] = Field(
        default=["AAPL", "MSFT", "NVDA", "SAP.DE", "ALV.DE"], min_length=1, max_length=20
    )
    start: date = date(2021, 8, 26)
    end: date = date(2026, 8, 25)
    horizon: Literal["next_day"] = "next_day"
    fee_bps: float = Field(default=2, ge=0, le=100, allow_inf_nan=False)
    spread_bps: float = Field(default=2, ge=0, le=100, allow_inf_nan=False)
    slippage_bps: float = Field(default=3, ge=0, le=100, allow_inf_nan=False)
    train_sessions: int = Field(default=252, ge=120, le=2000)
    calibration_sessions: int = Field(default=63, ge=30, le=252)
    test_sessions: int = Field(default=63, ge=20, le=252)
    top_k: int = Field(default=3, ge=1, le=20)

    @model_validator(mode="after")
    def dates_ordered(self):
        if self.start >= self.end:
            raise ValueError("Start muss vor Ende liegen")
        if len(set(self.tickers)) != len(self.tickers):
            raise ValueError("Doppelte Ticker")
        return self


def prepare(prices, instruments):
    pieces = []
    now = pd.Timestamp.now(tz="UTC")
    for ticker, frame in prices.groupby("ticker"):
        frame = frame.sort_values("trade_date").copy()
        frame["trade_date"] = pd.to_datetime(frame.trade_date)
        calendar = xcals.get_calendar(instruments[ticker]["calendar"])
        valid_dates = [
            d
            for d in frame.trade_date
            if calendar.is_session(d) and calendar.session_close(d) <= now
        ]
        frame = frame.loc[frame.trade_date.isin(valid_dates)].copy()
        features = calculate_features(frame)
        frame = frame.merge(features, on=["ticker", "trade_date"])
        frame["label_end"] = frame.trade_date.shift(-1)
        frame["next_open"] = frame.open_price.shift(-1)
        frame["next_close"] = frame.close_price.shift(-1)
        # Do not silently call the next available row the next session when bars are missing.
        next_sessions = frame.trade_date.map(lambda d: calendar.next_session(d).tz_localize(None))
        frame = frame.loc[frame.label_end == next_sessions]
        frame["execution_return"] = frame.next_close / frame.next_open - 1
        frame["forecast_at"] = frame.trade_date.map(lambda d: calendar.session_close(d).isoformat())
        frame["execution_at"] = frame.label_end.map(lambda d: calendar.session_open(d).isoformat())
        frame["outcome_at"] = frame.label_end.map(lambda d: calendar.session_close(d).isoformat())
        pieces.append(frame)
    if not pieces:
        raise ValueError("Keine historischen Kurse")
    return (
        pd.concat(pieces)
        .replace([np.inf, -np.inf], np.nan)
        .dropna(subset=[*FEATURE_COLUMNS, "target_next_day_up", "execution_return", "label_end"])
        .sort_values(["trade_date", "ticker"])
        .reset_index(drop=True)
    )


def partitions(frame, request):
    dates = np.array(sorted(frame.trade_date.unique()))
    first = request.train_sessions + request.calibration_sessions
    for pos in range(first, len(dates), request.test_sessions):
        cal_start = dates[pos - request.calibration_sessions]
        test_start = dates[pos]
        test_end = dates[min(pos + request.test_sessions, len(dates)) - 1]
        train = frame[(frame.trade_date < cal_start) & (frame.label_end < cal_start)]
        calibration = frame[
            (frame.trade_date >= cal_start)
            & (frame.trade_date < test_start)
            & (frame.label_end < test_start)
        ]
        test = frame[(frame.trade_date >= test_start) & (frame.trade_date <= test_end)]
        if len(train) and len(calibration) and len(test):
            yield train, calibration, test


def metrics(target, probability):
    predicted = probability >= 0.5
    return {
        "accuracy": float(accuracy_score(target, predicted)),
        "balanced_accuracy": float(balanced_accuracy_score(target, predicted)),
        "precision": float(precision_score(target, predicted, zero_division=0)),
        "recall": float(recall_score(target, predicted, zero_division=0)),
        "f1": float(f1_score(target, predicted, zero_division=0)),
        "roc_auc": float(roc_auc_score(target, probability)) if len(set(target)) == 2 else None,
        "brier_score": float(brier_score_loss(target, probability)),
        "confusion_matrix": confusion_matrix(target, predicted, labels=[0, 1]).tolist(),
    }


def logit(probability):
    p = np.clip(probability, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p)).reshape(-1, 1)


def research_estimator(model):
    """Shared fixed estimators for walk-forward and explicitly final research training."""
    if model not in {"logistic", "random_forest"}:
        raise ValueError("Unbekannter Forschungsmodelltyp")
    estimator = build_model()
    if model == "random_forest":
        estimator = Pipeline(
            [
                ("preprocessing", estimator.named_steps["preprocessing"]),
                (
                    "classifier",
                    RandomForestClassifier(
                        n_estimators=100,
                        max_depth=5,
                        min_samples_leaf=20,
                        random_state=42,
                        n_jobs=1,
                    ),
                ),
            ]
        )
    return estimator


def calibration_bins(target, probability):
    frame = pd.DataFrame({"actual": target, "probability": probability})
    bins = []
    for low in np.arange(0, 1, 0.1):
        subset = frame[(frame.probability >= low) & (frame.probability < low + 0.1)]
        if len(subset):
            bins.append(
                {"predicted": float(subset.probability.mean()),
                 "observed": float(subset.actual.mean()), "count": len(subset)}
            )
    return bins


def evaluate(prices, instruments, request, artifact_dir: Path | None = None):
    prices = prices.copy()
    prices["trade_date"] = pd.to_datetime(prices.trade_date)
    data_hash = digest(prices)
    if artifact_dir is not None:
        artifact_dir.mkdir(parents=True, exist_ok=False)
        prices.to_csv(artifact_dir / "input.csv", index=False)
    frame = prepare(prices, instruments)
    frame = frame[
        (frame.trade_date >= pd.Timestamp(request.start))
        & (frame.label_end <= pd.Timestamp(request.end))
    ]
    outputs, folds, importance = [], [], []
    inputs = [*FEATURE_COLUMNS, "ticker"]
    for number, (train, calibration, test) in enumerate(partitions(frame, request)):
        if train.target_next_day_up.nunique() < 2 or calibration.target_next_day_up.nunique() < 2:
            continue
        estimator = research_estimator(request.model)
        estimator.fit(train[inputs], train.target_next_day_up.astype(int))
        calibrator = LogisticRegression(random_state=42)
        calibrator.fit(
            logit(estimator.predict_proba(calibration[inputs])[:, 1]),
            calibration.target_next_day_up.astype(int),
        )
        probability = calibrator.predict_proba(logit(estimator.predict_proba(test[inputs])[:, 1]))[
            :, 1
        ]
        output = test[
            [
                "ticker",
                "trade_date",
                "label_end",
                "forecast_at",
                "execution_at",
                "outcome_at",
                "execution_return",
            ]
        ].copy()
        output["actual"] = test.target_next_day_up.astype(int)
        output["probability"] = probability
        output["naive_probability"] = float(train.target_next_day_up.astype(int).mean())
        output["fold"] = number
        if artifact_dir is not None:
            joblib.dump(
                {
                    "model": estimator,
                    "calibrator": calibrator,
                    "input_columns": inputs,
                    "fold": number,
                },
                artifact_dir / f"fold-{number:03d}.joblib",
                compress=3,
            )
        outputs.append(output)
        folds.append(
            {
                "fold": number,
                "train_start": str(train.trade_date.min().date()),
                "train_end": str(train.trade_date.max().date()),
                "train_label_end": str(train.label_end.max().date()),
                "calibration_start": str(calibration.trade_date.min().date()),
                "calibration_end": str(calibration.trade_date.max().date()),
                "calibration_label_end": str(calibration.label_end.max().date()),
                "test_start": str(test.trade_date.min().date()),
                "test_end": str(test.trade_date.max().date()),
                "train_rows": len(train),
                "test_rows": len(test),
            }
        )
        classifier = estimator.named_steps["classifier"]
        values = (
            classifier.feature_importances_
            if request.model == "random_forest"
            else classifier.coef_[0]
        )
        importance = [
            {"feature": name, "value": float(value)}
            for name, value in zip(
                estimator.named_steps["preprocessing"].get_feature_names_out(), values
            )
        ]
    if not outputs:
        raise ValueError(
            "Zu wenige vollständige Sitzungen oder Klassen für Training, Kalibrierung und Test"
        )
    result = pd.concat(outputs).sort_values(["trade_date", "ticker"])
    cost = (2 * request.fee_bps + request.spread_bps + 2 * request.slippage_bps) / 10000
    result["net_return"] = np.where(result.probability >= 0.5, result.execution_return - cost, 0)
    # Fixed universe sleeves, including cash for missing sessions and signals.
    daily = result.groupby("label_end").net_return.sum() / len(request.tickers)
    equity = (1 + daily).cumprod()
    peaks = equity.cummax().clip(lower=1)
    top = (
        result.sort_values("probability", ascending=False).groupby("trade_date").head(request.top_k)
    )
    score = metrics(result.actual.to_numpy(), result.probability.to_numpy())
    score.update(
        precision_at_k=float(top.actual.mean()),
        net_return=float(equity.iloc[-1] - 1),
        average_net_return=float(daily.mean()),
        max_drawdown=float((equity / peaks - 1).min()),
        average_excess_return=None,
    )
    bins = calibration_bins(result.actual.to_numpy(), result.probability.to_numpy())
    import sklearn

    import src.feature_engineering as feature_module

    code_hash = hashlib.sha256(
        Path(__file__).read_bytes() + Path(feature_module.__file__).read_bytes()
    ).hexdigest()
    provenance = {
        "request": request.model_dump(mode="json"),
        "data_hash": data_hash,
        "code_hash": code_hash,
        "calendars": {t: instruments[t]["calendar"] for t in request.tickers},
        "versions": {
            "sklearn": sklearn.__version__,
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "exchange_calendars": xcals.__version__,
        },
    }
    fingerprint = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()

    report = {
        "request": request.model_dump(mode="json"),
        "data_hash": data_hash,
        "reproducibility_key": fingerprint,
        "provenance": provenance,
        "model_version": f"{request.model}-wf-v1",
        "feature_version": "pipeline-six-v1",
        "seed": 42,
        "sklearn_version": sklearn.__version__,
        "metrics": score,
        "naive_metrics": metrics(result.actual.to_numpy(), result.naive_probability.to_numpy()),
        "folds": folds,
        "test_rows": len(result),
        "calibration": bins,
        "feature_importance": importance,
        "feature_importance_scope": "Letzter Walk-Forward-Fold; LR: standardisierte Koeffizienten, RF: impurity importance",
        "equity": [{"date": str(d.date()), "value": float(v)} for d, v in equity.items()],
        "predictions": records(result),
        "round_trip_cost_bps": cost * 10000,
        "status": "research_only",
        "forecast_enabled": False,
        "limitations": [
            "Keine unabhängige Modellfreigabe; kein Profitabilitätsnachweis.",
            "Ziel: nächster Schlusskurs höher als heutiger. Ausführung erst nächste Sitzung Open→Close.",
            "Adjustierte historische Snapshots: keine point-in-time Corporate-Action- oder Survivorship-Korrektur.",
            "Gleichgewichtete Währungssleeves; keine EUR/USD-Umrechnung oder Portfolio-Währungsrendite.",
            "Index-Überschussrendite und News-Modell fehlen: keine geeigneten zeitkorrekten Referenzdaten.",
        ],
    }
    if artifact_dir is not None:
        (artifact_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return report
