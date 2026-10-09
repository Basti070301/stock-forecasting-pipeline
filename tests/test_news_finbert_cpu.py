"""Opt-in real CPU inference, synthetic inputs only; no provider/live data claim."""

import os
from datetime import datetime, timedelta, timezone

import pytest

from src.platform.config import Settings
from src.platform.news import FINBERT_REVISION, Article, finbert
from src.platform.news_engine import NewsEngine
from src.platform.store import Store


@pytest.mark.skipif(
    os.getenv("SI_TEST_FINBERT_CPU") != "1",
    reason="Realer CPU-Modelltest nur explizit mit lokalem Cache",
)
def test_real_finbert_cpu_batch_and_language_skip(tmp_path):
    assert os.getenv("HF_HUB_OFFLINE") == "1", "Kein versteckter Modelldownload im Test"
    store = Store(Settings(runtime_dir=tmp_path, finbert_enabled=True, news_batch_size=2))
    store.migrate()
    now = datetime.now(timezone.utc)
    samples = [
        ("The company reported higher revenue and profit.", "en"),
        ("The company reported a significant loss and a decline in revenue.", "en"),
        ("Das Unternehmen berichtet über steigenden Umsatz.", "de"),
    ]
    engine = NewsEngine(store)
    engine.ingest(
        [
            Article(
                source="synthetic CPU smoke; not a real news source",
                title=title,
                url=f"https://example.com/synthetic-cpu/{index}",
                published_at=now - timedelta(hours=1),
                first_seen_at=now,
                tickers=["AAPL"],
                language=language,
                provider="synthetic-test",
                data_kind="fixture",
            )
            for index, (title, language) in enumerate(samples)
        ]
    )
    result = engine.analyze()
    assert result == {"analyzed": 2, "unsupported": 1}
    scores = store.all("sentiments")
    for score in scores:
        assert all(0 <= score[label] <= 1 for label in ("positive", "negative", "neutral"))
        assert sum(score[label] for label in ("positive", "negative", "neutral")) == pytest.approx(
            1, abs=0.001
        )
        assert score["sentiment"] == pytest.approx(score["positive"] - score["negative"])
        assert score["model_revision"] == FINBERT_REVISION
    assert str(finbert(-1).device) == "cpu"
    before = finbert.cache_info()
    assert engine.analyze()["analyzed"] == 0
    assert finbert.cache_info().misses == before.misses == 1
    assert engine.aggregate("AAPL", 7)["analyzed_count"] == 0, (
        "Synthetic inputs are never live aggregates"
    )
    store.engine.dispose()
