"""Provider fixtures are synthetic mocks, never a live-integration claim."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from src.platform.api import create_app
from src.platform.config import DEFAULT_INSTRUMENTS, Settings
from src.platform.news import FINBERT_REVISION, Article
from src.platform.news_engine import NewsEngine, same_story
from src.platform.news_providers import ApprovedRSS, Finnhub, ProviderError, map_companies
from src.platform.news_scheduler import NewsScheduler
from src.platform.store import Store

NOW = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)


def article(
    title="Microsoft reports higher revenue and profit for the quarter",
    url="https://example.com/news/1",
    language="en",
    tickers=None,
    published=None,
):
    return Article(
        source="Fixture source",
        title=title,
        url=url,
        description="",
        published_at=published or NOW - timedelta(hours=2),
        first_seen_at=max(NOW, published or NOW),
        tickers=tickers or ["MSFT"],
        language=language,
        provider="finnhub",
        mapping_evidence=[
            {"ticker": ticker, "method": "provider_ticker", "matched": ticker}
            for ticker in (tickers or ["MSFT"])
        ],
    )


class Classifier:
    def __init__(self):
        self.batches = []

    def __call__(self, texts, **kwargs):
        self.batches.append((texts, kwargs))
        return [
            [
                {"label": "positive", "score": 0.7},
                {"label": "negative", "score": 0.1},
                {"label": "neutral", "score": 0.2},
            ]
            for _ in texts
        ]


@pytest.fixture
def engine(tmp_path):
    store = Store(
        Settings(
            mode="demo",
            runtime_dir=tmp_path,
            news_enabled=True,
            news_rights_accepted=True,
            finnhub_key="fixture-only",
            finbert_enabled=True,
            news_batch_size=2,
        )
    )
    store.migrate()
    instance = NewsEngine(store, classifier=Classifier(), clock=lambda: NOW)
    yield instance
    store.engine.dispose()


def test_finnhub_parsing_exact_tickers_and_no_summary_by_default():
    row = {
        "headline": "Microsoft and NVIDIA announce a partnership for business customers",
        "source": "Fixture wire",
        "summary": "not licensed to store by default",
        "url": "https://example.com/story",
        "datetime": (datetime.now(timezone.utc) - timedelta(days=1)).timestamp(),
        "id": 123,
        "related": "MSFT,NVDA",
    }

    def response(request):
        assert request.headers["X-Finnhub-Token"] == "fixture-only"
        assert "token" not in request.url.query.decode()
        return httpx.Response(200, json=[row])

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        provider = Finnhub("fixture-only", client=client)
        result = provider.fetch(DEFAULT_INSTRUMENTS[1].model_dump())
    assert result[0].tickers == ["MSFT", "NVDA"]
    assert result[0].description == ""
    assert result[0].published_at.utcoffset().total_seconds() == 0
    assert result[0].first_seen_at >= result[0].published_at
    assert result[0].mapping_evidence[0]["method"] == "provider_ticker"


def test_missing_key_and_unsupported_european_symbol():
    with pytest.raises(ProviderError, match="Schlüssel fehlt"):
        Finnhub("").fetch(DEFAULT_INSTRUMENTS[0].model_dump())
    for instrument in DEFAULT_INSTRUMENTS[3:]:
        with pytest.raises(ProviderError, match="bestätigte US-Ticker"):
            Finnhub("fixture").fetch(instrument.model_dump())
    assert not map_companies(["AAPLX"], "The apple harvest and a microsoftish word are unrelated")
    assert {
        item["ticker"]
        for item in map_companies(text="Apple Inc. collaborates with Microsoft and Allianz SE")
    } == {"AAPL", "MSFT", "ALV.DE"}


@pytest.mark.parametrize("failure", ["timeout", "server"])
def test_bounded_retries_and_every_attempt_accounted(failure):
    calls, waits, reserved = [], [], []

    def response(request):
        calls.append(1)
        if len(calls) < 3:
            if failure == "timeout":
                raise httpx.ReadTimeout("fixture timeout", request=request)
            return httpx.Response(503)
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        assert (
            Finnhub(
                "fixture",
                client=client,
                sleep=waits.append,
                before_request=lambda: reserved.append(1),
            ).fetch(DEFAULT_INSTRUMENTS[0].model_dump())
            == []
        )
    assert len(calls) == len(reserved) == 3
    assert waits == [1, 2]


@pytest.mark.parametrize(
    "status,code", [(401, "http_error"), (429, "rate_limit"), (500, "http_5xx")]
)
def test_http_errors_no_key_or_payload_in_messages(status, code):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(status, headers={"Retry-After": "120"})
        )
    ) as client:
        with pytest.raises(ProviderError) as error:
            Finnhub("secret-fixture", client=client, sleep=lambda _: None).fetch(
                DEFAULT_INSTRUMENTS[0].model_dump()
            )
    assert error.value.code == code and "secret-fixture" not in str(error.value)
    if status == 429:
        assert error.value.cooldown == 120


def test_rss_timezone_safety_issuer_evidence_and_no_full_text():
    feed = {
        "url": "https://example.com/feed.xml",
        "name": "Fixture approved issuer",
        "ticker": "SAP.DE",
        "rights_confirmed": True,
        "license_reference": "fixture written permission",
    }
    xml = b"<rss><channel><item><title>SAP SE announces business software innovation</title><link>https://example.com/sap</link><pubDate>Thu, 01 Jan 2026 12:30:00 +0200</pubDate><description>full copyrighted article is not stored</description></item></channel></rss>"
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=xml))
    ) as client:
        rows = ApprovedRSS(feed, client=client).fetch({})
    assert rows[0].published_at.isoformat() == "2026-01-01T10:30:00+00:00"
    assert rows[0].description == ""
    assert rows[0].mapping_evidence[0]["method"] == "approved_issuer_feed"
    for bad in [
        {**feed, "rights_confirmed": False},
        {**feed, "url": "https://127.0.0.1/private"},
        {**feed, "url": "https://example.com/feed?token=fixture"},
    ]:
        with pytest.raises(ProviderError):
            ApprovedRSS(bad)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, content=b'<!DOCTYPE rss [<!ENTITY x "unsafe">]><rss/>')
        )
    ) as client:
        with pytest.raises(ProviderError, match="DTD"):
            ApprovedRSS(feed, client=client).fetch({})


def test_ingestion_updates_preserve_actual_first_seen_and_versions(engine):
    initial = article()
    assert engine.ingest([initial])["inserted"] == 1
    first = engine.store.all("news")[0]
    engine.clock = lambda: NOW + timedelta(hours=1)
    assert engine.ingest([initial])["inserted"] == 0
    changed = article(title="Microsoft reports a lower business profit forecast")
    assert engine.ingest([changed])["updated"] == 1
    current = engine.store.all("news")[0]
    assert current["first_seen_at"] == first["first_seen_at"] == NOW.isoformat()
    assert current["last_updated_at"] == (NOW + timedelta(hours=1)).isoformat()
    assert len(engine.store.all("news")) == 1
    assert engine.items(NOW + timedelta(minutes=30))[0]["title"] == initial.title
    assert engine.items(NOW + timedelta(hours=2))[0]["title"] == changed.title


def test_future_observation_and_analysis_never_leak_to_historical_snapshot(engine):
    engine.ingest([article(published=NOW - timedelta(days=10))])
    assert engine.items(NOW - timedelta(minutes=1)) == []
    engine.clock = lambda: NOW + timedelta(minutes=10)
    engine.analyze()
    assert engine.items(NOW + timedelta(minutes=5))[0]["analysis"] is None
    assert engine.aggregate("MSFT", 30, NOW + timedelta(minutes=5))["mean_sentiment"] is None
    assert engine.aggregate("MSFT", 30, NOW + timedelta(minutes=11))["analyzed_count"] == 1


def test_batch_languages_reanalysis_and_score_provenance(engine):
    engine.ingest(
        [
            article(),
            article(
                url="https://example.com/2",
                title="NVIDIA reports higher revenue for the recent financial quarter",
            ),
            article(
                url="https://example.com/de",
                title="Allianz meldet steigenden Umsatz",
                language="de",
                tickers=["ALV.DE"],
            ),
        ]
    )
    result = engine.analyze()
    assert result == {"analyzed": 2, "unsupported": 1}
    assert len(engine.classifier.batches) == 1 and len(engine.classifier.batches[0][0]) == 2
    assert engine.classifier.batches[0][1]["batch_size"] == 2
    scores = engine.store.all("sentiments")
    assert all(
        score["sentiment"] == pytest.approx(0.6) and score["dominant"] == "positive"
        for score in scores
    )
    assert all(
        score["model_revision"] == FINBERT_REVISION and score["input_hash"] for score in scores
    )
    assert engine.analyze()["analyzed"] == 0
    assert next(item for item in engine.items() if item["language"] == "de")["analysis"] is None
    engine.ingest([article(title="Microsoft reports a lower forecast for operating profit")])
    assert next(item for item in engine.items() if item["url"].endswith("/1"))["analysis"] is None
    assert engine.analyze()["analyzed"] == 1


def test_aggregation_deduplicates_excludes_unsupported_and_records_basis(engine):
    first = article()
    duplicate = article(url="https://example.com/reposted", title=first.title + "!")
    engine.ingest(
        [
            first,
            duplicate,
            article(
                url="https://example.com/other",
                title="Microsoft appoints a new chief financial officer for the business",
            ),
            article(url="https://example.com/de", language="de"),
        ]
    )
    engine.analyze()
    result = engine.aggregate("MSFT", 7)
    assert result["analyzed_count"] == 2 and result["duplicate_count"] == 2
    assert result["mean_sentiment"] == pytest.approx(0.6)
    assert result["positive"] == 2 and result["negative"] == result["neutral"] == 0
    assert len(result["basis"]["analysis_ids"]) == 2
    assert result["low_sample"] and len(result["basis_hash"]) == 64
    assert len(engine.store.all("news_aggregates")) == 15
    assert not same_story(
        article(title="Microsoft reports revenue growth of 10 percent").model_dump(),
        article(title="Microsoft reports revenue growth of 11 percent").model_dump(),
    )


def test_database_lease_blocks_other_process_and_releases_on_error(engine):
    other = NewsEngine(engine.store, clock=lambda: NOW)
    with pytest.raises(RuntimeError):
        with engine.lease():
            with pytest.raises(ValueError, match="parallel"):
                with other.lease():
                    pass
            raise RuntimeError("fixture failure")
    with other.lease():
        assert other.owner
    assert engine.store.all("news_locks") == []


def test_provider_status_errors_cooldown_and_daily_budget(engine):
    class Broken:
        def fetch(self, instrument):
            raise ProviderError("rate_limit", "fixture rate limit", 120)

    engine.injected_providers = {"finnhub": Broken()}
    report = engine.refresh("MSFT")
    assert report["errors"][0]["code"] == "rate_limit"
    assert engine.statuses()["providers"][0]["last_error"]["code"] == "rate_limit"
    assert engine.refresh("MSFT")["errors"][0]["code"] == "cooldown"
    engine.store.settings.news_daily_budget = 1
    engine.clock = lambda: datetime.now(timezone.utc)
    with engine.lease():
        engine.reserve("finnhub")
        with pytest.raises(ProviderError, match="Tagesbudget"):
            engine.reserve("finnhub")


def test_paginated_feed_filters_and_api_no_secrets(engine):
    engine.clock = lambda: datetime.now(timezone.utc)
    engine.ingest(
        [
            article(published=datetime.now(timezone.utc) - timedelta(hours=2)),
            article(
                url="https://example.com/2",
                title="NVIDIA reports financial results",
                published=datetime.now(timezone.utc) - timedelta(hours=2),
                tickers=["NVDA"],
            ),
            article(
                url="https://example.com/de",
                language="de",
                tickers=["ALV.DE"],
                published=datetime.now(timezone.utc) - timedelta(hours=2),
            ),
        ]
    )
    engine.analyze()
    with TestClient(create_app(engine.settings, engine.store)) as client:
        response = client.get("/api/news/feed?page_size=1")
        assert response.status_code == 200 and response.json()["total"] == 3
        snapshot = response.json()["as_of"]
        assert (
            client.get(
                "/api/news/feed", params={"page_size": 1, "page": 2, "as_of": snapshot}
            ).json()["items"][0]["id"]
            != response.json()["items"][0]["id"]
        )
        assert client.get("/api/news/feed?ticker=ALV.DE&sentiment=unavailable").json()["total"] == 1
        assert client.get("/api/news/feed?ticker=MSFT&sentiment=positive").json()["total"] == 1
        assert client.get("/api/news/feed?source=unknown").json()["total"] == 0
        assert client.get("/api/news/feed?page=0").status_code == 422
        assert client.get("/api/news/feed?as_of=2026-01-01").status_code == 422
        assert client.get("/api/news/feed?ticker=UNKNOWN").status_code == 404
        assert client.get("/api/stocks/MSFT/sentiment").json()["windows"][1]["analyzed_count"] == 1
        assert client.get("/api/news/summary").status_code == 200
        providers = client.get("/api/news/providers")
        assert "fixture-only" not in providers.text
        assert client.post("/api/news/refresh", json={"ticker": "SAP.DE"}).status_code == 409


def test_missing_configuration_does_not_stop_app_or_invent_news(tmp_path):
    settings = Settings(runtime_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/news/feed").json()["items"] == []
        assert client.get("/api/news/providers").json()["providers"][0]["configured"] is False
        assert (
            client.get("/api/stocks/AAPL/sentiment").json()["windows"][0]["mean_sentiment"] is None
        )
        assert client.post("/api/news/refresh", json={"ticker": "AAPL"}).status_code == 409


def test_scheduler_is_bounded_and_skips_busy_executor(engine):
    class Busy:
        def submit(self, *args):
            raise ValueError("busy")

    scheduler = NewsScheduler(engine.store, Busy())
    assert scheduler.tick() is False
    scheduler.stop_event.set()
    scheduler.run()
    assert scheduler.cycles == 0


def test_revision_transaction_rolls_back_on_failure(engine, monkeypatch):
    original = engine.store.add

    def broken(name, *args, **kwargs):
        if name == "news_revisions":
            raise RuntimeError("fixture failed revision write")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(engine.store, "add", broken)
    with pytest.raises(RuntimeError):
        engine.ingest([article()])
    assert engine.store.all("news") == [] and engine.store.all("news_links") == []


def test_unsupported_refresh_and_unconfirmed_rights_are_explicit(engine):
    with pytest.raises(ValueError, match="Zuordnung"):
        engine.refresh("SAP.DE")
    engine.ingest([article()])
    engine.store.settings.news_rights_accepted = False
    assert engine.items() == []
    with pytest.raises(ValueError, match="Analyserechte"):
        engine.analyze()


def test_stream_size_invalid_payload_and_log_redaction():
    import logging

    from src.platform.news_providers import RedactQueryKeys

    for content, message in [
        (b"x" * (2 * 1024 * 1024 + 1), "2 MiB"),
        (b"not json", "JSON"),
        (b"{}", "Nachrichtenliste"),
    ]:
        with httpx.Client(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, content=content))
        ) as client:
            with pytest.raises(ProviderError, match=message):
                Finnhub("fixture", client=client).fetch(DEFAULT_INSTRUMENTS[0].model_dump())
    record = logging.LogRecord(
        "httpx", logging.INFO, "", 0, "GET https://example.com?apikey=do-not-log&x=1", (), None
    )
    RedactQueryKeys().filter(record)
    assert "do-not-log" not in record.getMessage()
    with pytest.raises(ValueError, match="Zugangsschlüssel"):
        article(url="https://example.com/news?token=do-not-store")


def test_scheduler_finishes_after_configured_attempts(engine):
    class Jobs:
        def __init__(self):
            self.calls = 0

        def submit(self, *args):
            self.calls += 1

    jobs = Jobs()
    scheduler = NewsScheduler(engine.store, jobs)
    engine.settings.news_max_cycles = 3

    class Event:
        def is_set(self):
            return False

        def wait(self, seconds):
            return False

    scheduler.stop_event = Event()
    scheduler.run()
    assert jobs.calls == scheduler.cycles == 3


def test_near_duplicate_does_not_merge_opposite_polarity_or_late_reposts(engine):
    assert not same_story(
        article(
            title="Microsoft reports higher revenue and earnings for this quarter"
        ).model_dump(),
        article(title="Microsoft reports lower revenue and earnings for this quarter").model_dump(),
    )
    engine.ingest([article(published=NOW - timedelta(hours=30))])
    engine.analyze()
    engine.clock = lambda: NOW + timedelta(hours=1)
    engine.ingest([article(url="https://example.com/repost", published=NOW - timedelta(hours=1))])
    engine.analyze()
    assert engine.aggregate("MSFT", 1)["analyzed_count"] == 0


def test_mock_http_to_persistent_news_analysis_and_provider_status(engine):
    engine.clock = lambda: datetime.now(timezone.utc)
    payload = [
        {
            "headline": "Microsoft announces higher revenue and profit during quarterly financial reporting",
            "url": "https://example.com/mocked-integration",
            "source": "Mock integration wire",
            "datetime": (datetime.now(timezone.utc) - timedelta(hours=2)).timestamp(),
            "id": 99,
            "related": "MSFT",
        }
    ]
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    ) as client:
        engine.injected_providers = {
            "finnhub": Finnhub(
                "fixture-only", client=client, before_request=lambda: engine.reserve("finnhub")
            )
        }
        report = engine.refresh("MSFT", strict=True)
    assert (
        report["received"]
        == report["inserted"]
        == report["analyzed"]
        == report["successful_requests"]
        == 1
    )
    assert report["errors"] == [] and report["partial"] is False
    assert len(engine.store.all("provider_calls")) == 1
    assert engine.statuses()["providers"][0]["last_success"] is not None
    reopened = Store(engine.settings)
    try:
        persisted = NewsEngine(reopened).items()[0]
        assert persisted["analysis"]["sentiment"] == pytest.approx(0.6)
        assert persisted["first_seen_at"] == engine.store.all("news")[0]["first_seen_at"]
    finally:
        reopened.engine.dispose()
