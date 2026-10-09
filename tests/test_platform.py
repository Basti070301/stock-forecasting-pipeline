import time
from datetime import datetime, timezone

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from src.platform.api import create_app
from src.platform.config import DEFAULT_INSTRUMENTS, Settings
from src.platform.intraday import horizon_end, validate_minute_bars
from src.platform.jobs import Jobs
from src.platform.market import MarketService, demo_prices
from src.platform.news import AlphaVantage, Article, analyze, article_id, score_labels
from src.platform.research import BacktestRequest, evaluate, partitions, prepare
from src.platform.store import Store


@pytest.fixture
def store(tmp_path):
    store = Store(Settings(runtime_dir=tmp_path, mode="demo"))
    store.migrate()
    yield store
    store.engine.dispose()


@pytest.fixture
def client(store):
    with TestClient(create_app(store.settings, store)) as client:
        yield client


def test_migration_is_additive_and_repeatable(store):
    with store.engine.begin() as conn:
        conn.execute(text("CREATE TABLE legacy_marker (value INTEGER)"))
        conn.execute(text("INSERT INTO legacy_marker VALUES (42)"))
    store.migrate()
    assert len(store.instruments()) == 5
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT value FROM legacy_marker")).scalar_one() == 42
    assert "si_news" in inspect(store.engine).get_table_names()


def test_immutable_forecasts_and_separate_outcomes(store):
    store.add("forecasts", {"ticker": "AAPL", "probability": 0.55}, "f1")
    store.add("forecasts", {"ticker": "AAPL", "probability": 0.99}, "f1")
    assert store.get("forecasts", "f1")["probability"] == 0.55
    with pytest.raises(ValueError):
        store.update("forecasts", "f1", {"probability": 0.99})
    store.add("outcomes", {"forecast_id": "f1", "actual": 1}, "f1")
    assert store.get("forecasts", "f1")["probability"] == 0.55


def test_demo_live_isolation(store):
    live = Store(Settings(mode="live"), engine=store.engine)
    live.migrate()
    store.add("news", {"title": "Demo example"}, "n1")
    assert live.list("news") == []
    assert len(live.instruments()) == 5


def test_routes_and_actual_snapshot(client):
    assert client.get("/api/health").json()["mode"] == "demo"
    rows = client.get("/api/stocks").json()
    assert len(rows) == 5
    assert sum(r["quality"]["rows"] for r in rows) == 6312
    aapl = next(r for r in rows if r["ticker"] == "AAPL")
    assert aapl["price"] == float(demo_prices("AAPL").iloc[-1].close_price)
    assert aapl["forecast_probability"] is None
    assert client.get("/api/stocks/AAPL/history?limit=21").json()["data"].__len__() == 21
    assert client.get("/api/stocks/AAPL/history?interval=1m").status_code == 422
    assert client.get("/api/stocks/UNKNOWN").status_code == 404
    assert client.get("/api/stocks/AAPL/news").json() == []
    assert client.get("/api/forecasts").json()["items"] == []
    assert client.get("/api/models").json()[0]["metrics"]["accuracy"] == pytest.approx(
        0.51905920519
    )
    for endpoint in ("/api/backtests", "/api/news", "/api/pipeline/status", "/api/settings"):
        assert client.get(endpoint).status_code == 200


def test_filters_and_score_transparency(client):
    rows = client.get("/api/radar?region=Europa").json()["items"]
    assert {r["ticker"] for r in rows} == {"SAP.DE", "ALV.DE"}
    assert client.get("/api/radar?sentiment=positive").json()["items"] == []
    assert client.get("/api/radar?horizon=60m").json()["items"] == []
    for row in rows:
        assert row["radar_score"] == round(
            sum(v for v in row["components"].values() if v is not None), 1
        )
        assert row["news_sentiment"] is None


def test_mutation_security_and_validation(client):
    invalid = {**DEFAULT_INSTRUMENTS[0].model_dump(), "timezone": "Invalid/TimeZone"}
    assert client.post("/api/settings/watchlist", json=invalid).status_code == 422
    assert (
        client.post(
            "/api/pipeline/refresh", headers={"Origin": "https://evil.example"}, json={}
        ).status_code
        == 403
    )
    assert client.post("/api/news/refresh", json={"ticker": "AAPL"}).status_code == 409
    assert client.post("/api/news/analyze", json={}).status_code == 409
    assert client.post("/api/settings/watchlist", json={"ticker": "../../etc"}).status_code == 422
    assert client.post("/api/backtests", json={"fee_bps": -1}).status_code == 422
    assert (
        client.post("/api/backtests", json={"start": "2026-01-01", "end": "2025-01-01"}).status_code
        == 422
    )
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400


def test_token_not_exposed_and_required(store):
    settings = Settings(runtime_dir=store.settings.runtime_dir, mutation_token="private-test-token")
    with TestClient(create_app(settings, store)) as client:
        response = client.get("/api/settings")
        assert "private-test-token" not in response.text
        assert client.post("/api/pipeline/refresh", json={}).status_code == 403
        assert (
            client.post(
                "/api/pipeline/refresh", json={}, headers={"X-SI-Token": "private-test-token"}
            ).status_code
            == 202
        )


def test_pipeline_job_completes(client):
    response = client.post("/api/pipeline/refresh", json={})
    assert response.status_code == 202
    identity = response.json()["job_id"]
    for _ in range(100):
        job = client.get(f"/api/jobs/{identity}").json()
        if job["status"] == "succeeded":
            break
        time.sleep(0.01)
    assert job["status"] == "succeeded"
    assert job["result"]["rows"] == 6312


def test_jobs_restart_and_failures(store):
    store.add("jobs", {"kind": "test", "status": "running"}, "interrupted")
    jobs = Jobs(store)
    assert store.get("jobs", "interrupted")["status"] == "interrupted"

    def fail():
        raise RuntimeError("secret-password")

    result = jobs.submit("test", fail)
    jobs.close()
    saved = store.get("jobs", result["job_id"])
    assert saved["status"] == "failed"
    assert "secret-password" not in saved["error"]


def test_provider_mapping_dedup_utc_and_scores(store):
    payload = {
        "feed": [
            {
                "title": "Apple reports strong quarterly revenue growth and higher profits",
                "summary": "The company reported revenue growth in all of its major business segments.",
                "url": "https://example.com/news?a=1&utm_source=test",
                "source": "Test fixture",
                "time_published": "20260825T120000",
                "ticker_sentiment": [{"ticker": "AAPL"}],
            }
        ]
    }
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as client:
        rows = AlphaVantage("fixture-key", client).fetch(DEFAULT_INSTRUMENTS[0].model_dump())
    assert len(rows) == 1 and rows[0].language == "en"
    assert rows[0].published_at.utcoffset().total_seconds() == 0
    changed = Article.model_validate(
        {**rows[0].model_dump(), "url": "https://example.com/news?a=1"}
    )
    assert article_id(rows[0]) == article_id(changed)
    store.add("news", rows[0].model_dump(mode="json"), article_id(rows[0]))
    first = store.list("news")[0]["first_seen_at"]
    store.add("news", changed.model_dump(mode="json"), article_id(changed))
    assert len(store.list("news")) == 1
    assert store.list("news")[0]["first_seen_at"] == first
    score = analyze(
        {**rows[0].model_dump(), "id": "n"},
        classifier=lambda *a, **kw: [
            {"label": "neutral", "score": 0.2},
            {"label": "negative", "score": 0.1},
            {"label": "positive", "score": 0.7},
        ],
    )
    assert score["sentiment"] == pytest.approx(0.6)
    assert analyze({"language": "de"}) is None
    assert (
        score_labels(
            [
                {"label": "positive", "score": 0.7},
                {"label": "negative", "score": 0.1},
                {"label": "neutral", "score": 0.2},
            ]
        )["positive"]
        == 0.7
    )
    with pytest.raises(ValueError):
        score_labels([{"label": "positive", "score": 3}])


def test_news_temporal_validation():
    with pytest.raises(ValueError):
        Article(
            source="test",
            title="test",
            url="https://example.com",
            tickers=["AAPL"],
            language="en",
            published_at="2026-09-01T00:00:00Z",
            first_seen_at="2026-08-01T00:00:00Z",
        )
    with pytest.raises(ValueError):
        Article(
            source="test",
            title="test",
            url="https://example.com",
            tickers=["AAPL"],
            language="en",
            published_at="2026-01-01",
            first_seen_at=datetime.now(timezone.utc),
        )


def test_provider_retries_and_rate_limits():
    count = []

    def transport(request):
        count.append(1)
        return httpx.Response(503 if len(count) < 3 else 200, json={"feed": []})

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        assert (
            AlphaVantage("key", client, sleep=lambda _: None).fetch(
                DEFAULT_INSTRUMENTS[0].model_dump()
            )
            == []
        )
    assert len(count) == 3
    for response in [httpx.Response(429), httpx.Response(200, json={"Information": "premium"})]:
        with httpx.Client(transport=httpx.MockTransport(lambda r: response)) as client:
            with pytest.raises(ValueError):
                AlphaVantage("key", client).fetch(DEFAULT_INSTRUMENTS[0].model_dump())


def test_purging_and_missing_sessions():
    prices = demo_prices("AAPL").head(450)
    config = {i.ticker: i.model_dump() for i in DEFAULT_INSTRUMENTS}
    frame = prepare(prices, config)
    request = BacktestRequest(
        tickers=["AAPL"], train_sessions=120, calibration_sessions=30, test_sessions=63
    )
    for train, calibration, test in partitions(frame, request):
        assert train.label_end.max() < calibration.trade_date.min()
        assert calibration.label_end.max() < test.trade_date.min()
    missing_day = pd.Timestamp(prices.iloc[200].trade_date)
    previous_day = pd.Timestamp(prices.iloc[199].trade_date)
    broken = prepare(prices.drop(prices.index[200]), config)
    assert previous_day not in set(broken.trade_date)
    assert missing_day not in set(broken.trade_date)


@pytest.mark.parametrize("model", ["logistic", "random_forest"])
def test_backtest_reproducible_costs_and_metrics(model):
    prices = demo_prices("AAPL").head(260)
    config = {i.ticker: i.model_dump() for i in DEFAULT_INSTRUMENTS}
    request = BacktestRequest(
        model=model, tickers=["AAPL"], train_sessions=120, calibration_sessions=30, test_sessions=63
    )
    result = evaluate(prices, config, request)
    repeat = evaluate(prices, config, request)
    assert result["metrics"] == repeat["metrics"]
    assert result["reproducibility_key"] == repeat["reproducibility_key"]
    assert result["round_trip_cost_bps"] == pytest.approx(12)
    assert result["forecast_enabled"] is False
    assert result["metrics"]["average_excess_return"] is None
    assert result["metrics"]["max_drawdown"] <= 0
    assert result["metrics"]["brier_score"] >= 0
    zero = evaluate(
        prices,
        config,
        request.model_copy(update={"fee_bps": 0, "spread_bps": 0, "slippage_bps": 0}),
    )
    assert zero["metrics"]["net_return"] >= result["metrics"]["net_return"]
    for row in result["predictions"]:
        expected = row["execution_return"] - 0.0012 if row["probability"] >= 0.5 else 0
        assert row["net_return"] == pytest.approx(expected, abs=1e-9)


def test_future_changes_do_not_change_earlier_features():
    prices = demo_prices("AAPL").head(260).copy()
    config = {i.ticker: i.model_dump() for i in DEFAULT_INSTRUMENTS}
    before = prepare(prices, config)
    prices.loc[prices.index[-5:], "close_price"] *= 1.1
    after = prepare(prices, config)
    pd.testing.assert_frame_equal(before.iloc[:-6], after.iloc[:-6])


def test_intraday_boundary_calendar():
    with pytest.raises(ValueError, match="geeignete Marktdaten"):
        validate_minute_bars(demo_prices("AAPL"), "XNYS")
    end = horizon_end("2026-08-25T14:00:00Z", 60, "XNYS")
    assert end == pd.Timestamp("2026-08-25T15:00:00Z")
    with pytest.raises(ValueError):
        horizon_end("2026-08-25T19:30:00Z", 120, "XNYS")


def test_live_reads_existing_tables_without_demo_fallback(store):
    live = Store(Settings(mode="live"), engine=store.engine)
    live.migrate()
    with live.engine.begin() as conn:
        conn.execute(text("CREATE TABLE dim_stock (stock_id INTEGER, ticker TEXT)"))
        conn.execute(
            text(
                "CREATE TABLE fact_stock_price (stock_id INTEGER, trade_date TEXT, open_price REAL, high_price REAL, low_price REAL, close_price REAL, volume INTEGER)"
            )
        )
        conn.execute(text("INSERT INTO dim_stock VALUES (1, 'AAPL')"))
        conn.execute(
            text("INSERT INTO fact_stock_price VALUES (1, '2026-08-25', 10, 12, 9, 11, 100)")
        )
    service = MarketService(live)
    assert service.prices("AAPL").close_price.iloc[0] == 11
    assert service.prices("MSFT").empty
