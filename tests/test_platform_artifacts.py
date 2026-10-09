import json

import joblib
import pandas as pd
import pytest

from src.platform.config import DEFAULT_INSTRUMENTS, Settings
from src.platform.intraday import validate_minute_bars
from src.platform.jobs import Jobs
from src.platform.market import demo_prices
from src.platform.news import Article
from src.platform.research import BacktestRequest, evaluate
from src.platform.store import Store


def test_backtest_archives_input_models_and_point_in_time_metadata(tmp_path):
    instruments = {i.ticker: i.model_dump() for i in DEFAULT_INSTRUMENTS}
    report = evaluate(
        demo_prices("AAPL").head(260),
        instruments,
        BacktestRequest(
            tickers=["AAPL"], train_sessions=120, calibration_sessions=30, test_sessions=63
        ),
        artifact_dir=tmp_path / "run",
    )
    stored = json.loads((tmp_path / "run" / "report.json").read_text(encoding="utf-8"))
    assert stored["reproducibility_key"] == report["reproducibility_key"]
    assert len(pd.read_csv(tmp_path / "run" / "input.csv")) == 260
    model = joblib.load(tmp_path / "run" / "fold-000.joblib")
    assert set(model) == {"model", "calibrator", "input_columns", "fold"}
    for prediction in report["predictions"]:
        assert pd.Timestamp(prediction["forecast_at"]) < pd.Timestamp(prediction["execution_at"])
        assert pd.Timestamp(prediction["execution_at"]) < pd.Timestamp(prediction["outcome_at"])
    with pytest.raises(FileExistsError):
        evaluate(
            demo_prices("AAPL").head(260),
            instruments,
            BacktestRequest(),
            artifact_dir=tmp_path / "run",
        )


def test_failed_pipeline_keeps_completed_steps(tmp_path):
    store = Store(Settings(runtime_dir=tmp_path))
    store.migrate()
    jobs = Jobs(store)

    def fail(progress):
        progress("Ingestion", "succeeded", 10)
        progress("Features", "running")
        raise ValueError("Testfehler")

    identity = jobs.submit("pipeline", fail, with_progress=True)["job_id"]
    jobs.close()
    result = store.get("jobs", identity)
    assert result["status"] == "failed"
    assert result["steps"][0]["status"] == "succeeded"
    assert result["steps"][0]["rows"] == 10
    assert result["steps"][1]["status"] == "failed"
    store.engine.dispose()


def test_news_offsets_are_normalized_to_utc():
    article = Article(
        source="fixture",
        title="fixture",
        url="https://example.com",
        tickers=[],
        language="de",
        published_at="2026-08-25T15:00:00+02:00",
        first_seen_at="2026-08-25T16:00:00+02:00",
    )
    assert article.published_at.hour == 13
    assert article.first_seen_at.hour == 14
    assert article.published_at.utcoffset().total_seconds() == 0


def test_minute_data_rejects_gaps_and_invalid_prices():
    bars = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-08-25T14:00:00Z", periods=130, freq="min"),
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10,
            "volume": 100,
        }
    )
    assert len(validate_minute_bars(bars, "XNYS")) == 130
    with pytest.raises(ValueError, match="Lücken"):
        validate_minute_bars(bars.drop(index=50), "XNYS")
    bars.loc[0, "high"] = 5
    with pytest.raises(ValueError, match="Inkonsistente"):
        validate_minute_bars(bars, "XNYS")
