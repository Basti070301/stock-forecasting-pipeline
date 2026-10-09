import hashlib
import logging
import math
import os
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from langdetect import DetectorFactory, detect_langs
from pydantic import AwareDatetime, BaseModel, Field, HttpUrl, field_validator, model_validator

from .store import utcnow

DetectorFactory.seed = 42


class Article(BaseModel):
    source: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=1000)
    description: str = Field(default="", max_length=20000)
    url: HttpUrl
    published_at: AwareDatetime
    first_seen_at: AwareDatetime
    tickers: list[str]
    language: str
    event_type: str | None = None
    provider: str = "alpha_vantage"

    @field_validator("published_at", "first_seen_at")
    @classmethod
    def normalize_utc(cls, value):
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def chronology(self):
        if self.published_at > self.first_seen_at:
            raise ValueError("Veröffentlichungszeit liegt nach Erfassung")
        return self


def canonical_url(url):
    parts = urlsplit(str(url))
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query)
        if not k.startswith("utm_") and k not in {"ref", "fbclid"}
    ]
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(sorted(query)), "")
    )


def article_id(article):
    return hashlib.sha256(canonical_url(article.url).encode()).hexdigest()


class NewsProvider(Protocol):
    def fetch(self, instrument: dict) -> list[Article]: ...


class AlphaVantage:
    def __init__(self, key, client=None, sleep=time.sleep):
        self.key = key
        self.client = client
        self.sleep = sleep

    def fetch(self, instrument):
        if not self.key:
            raise ValueError("Alpha Vantage: API-Schlüssel fehlt")
        symbol = instrument.get("news_symbol")
        if not symbol:
            raise ValueError("Keine bestätigte News-Ticker-Zuordnung für diesen Handelsplatz")
        payload = None
        for attempt in range(3):
            try:

                def request(client):
                    return client.get(
                        "https://www.alphavantage.co/query",
                        params={
                            "function": "NEWS_SENTIMENT",
                            "tickers": symbol,
                            "sort": "LATEST",
                            "limit": 50,
                            "apikey": self.key,
                        },
                    )

                if self.client:
                    response = request(self.client)
                else:
                    with httpx.Client(timeout=20) as client:
                        response = request(client)
                if response.status_code == 429:
                    raise ValueError("Alpha Vantage: Rate-Limit erreicht; später erneut abrufen")
                if response.status_code >= 500:
                    raise httpx.TransportError("Temporärer Providerfehler")
                if response.status_code != 200:
                    raise ValueError(f"Alpha Vantage: HTTP {response.status_code}")
                payload = response.json()
                break
            except httpx.TransportError:
                if attempt == 2:
                    raise ValueError("Alpha Vantage vorübergehend nicht erreichbar") from None
                self.sleep(2**attempt)
        if not isinstance(payload, dict) or any(
            k in payload for k in ("Note", "Information", "Error Message")
        ):
            raise ValueError(
                "Alpha Vantage: Zugriff oder Kontingent prüfen; NEWS_SENTIMENT benötigt passenden Tarif"
            )
        if "feed" not in payload:
            raise ValueError("Alpha Vantage lieferte keine gültige News-Antwort")
        seen = datetime.now(timezone.utc)
        articles = []
        for item in payload["feed"]:
            if symbol not in {t.get("ticker") for t in item.get("ticker_sentiment", [])}:
                continue
            try:
                content = item["title"] + " " + item.get("summary", "")
                detected = detect_langs(content)
                language = detected[0].lang if detected and detected[0].prob >= 0.9 else "unknown"
                articles.append(
                    Article(
                        source=item["source"],
                        title=item["title"],
                        description=item.get("summary", ""),
                        url=item["url"],
                        published_at=datetime.strptime(
                            item["time_published"], "%Y%m%dT%H%M%S"
                        ).replace(tzinfo=timezone.utc),
                        first_seen_at=seen,
                        tickers=[instrument["ticker"]],
                        language=language,
                        event_type=next(
                            (
                                t["topic"]
                                for t in item.get("topics", [])
                                if t["topic"] in {"earnings", "ipo", "mergers_and_acquisitions"}
                            ),
                            None,
                        ),
                    )
                )
            except (ValueError, KeyError):
                logging.warning(
                    "Ungültiger News-Datensatz verworfen (keine Provider-Payload protokolliert)"
                )
        return articles


_model_lock = Lock()
FINBERT_REVISION = "4556d13015211d73dccd3fdd39d39232506f3e43"


def finbert_options():
    from src.config import PROJECT_ROOT

    # Preserve the already-populated Windows cache; Docker uses standard HF_HOME/hub.
    cache = (
        Path(os.environ["HF_HOME"]) / "hub"
        if os.getenv("HF_HOME")
        else PROJECT_ROOT / ".cache" / "huggingface"
    )
    return {
        "cache_dir": Path(os.environ.get("HF_HUB_CACHE", str(cache))),
        "revision": FINBERT_REVISION,
        "local_files_only": os.getenv("HF_HUB_OFFLINE", "0").upper() in {"1", "TRUE", "YES"},
    }


@lru_cache(maxsize=1)
def finbert(device=-1):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline

    try:
        tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert", **finbert_options())
        model = AutoModelForSequenceClassification.from_pretrained(
            "ProsusAI/finbert", **finbert_options()
        )
    except OSError:
        raise ValueError(
            "FinBERT-Gewichte fehlen oder sind nicht lesbar. Modell explizit mit "
            "HF_HUB_OFFLINE=0 python -m src.platform.maintenance download-model laden; "
            "anschließend dasselbe HF_HOME-Volume verwenden."
        ) from None
    return pipeline(
        "text-classification",
        model=model,
        tokenizer=tokenizer,
        device=device if device >= 0 and torch.cuda.is_available() else -1,
    )


def score_labels(labels):
    scores = {x["label"].lower(): float(x["score"]) for x in labels}
    if (
        set(scores) != {"positive", "negative", "neutral"}
        or not all(math.isfinite(v) and 0 <= v <= 1 for v in scores.values())
        or abs(sum(scores.values()) - 1) > 0.01
    ):
        raise ValueError("Ungültige FinBERT-Ausgabe")
    return {
        **scores,
        "sentiment": scores["positive"] - scores["negative"],
        "model": "ProsusAI/finbert",
    }


def analyze(article, device=-1, classifier=None):
    if article["language"] != "en":
        return None
    with _model_lock:
        classifier = classifier or finbert(device)
        labels = classifier(
            article["title"] + ". " + article["description"],
            top_k=None,
            truncation=True,
            max_length=512,
        )
    revision = getattr(
        getattr(getattr(classifier, "model", None), "config", None), "_commit_hash", None
    )
    return {
        **score_labels(labels),
        "analyzed_at": utcnow(),
        "news_id": article["id"],
        "model_revision": revision,
    }


def collect_news(store, instrument, provider=None):
    if store.settings.mode != "live":
        raise ValueError("Demo-Modus: externe News-Abfragen deaktiviert")
    # Reserve a call before network access; persists across restarts. Conservative local cap.
    calls = store.list("provider_calls", 100)
    now = datetime.now(timezone.utc)
    if any((now - datetime.fromisoformat(c["created_at"])).total_seconds() < 60 for c in calls):
        raise ValueError("News-Abruf frühestens nach 60 Sekunden erneut möglich")
    if sum(c["created_at"][:10] == now.date().isoformat() for c in calls) >= 25:
        raise ValueError("Lokales Tagesbudget von 25 News-Abrufen erreicht")
    store.add("provider_calls", {"provider": "alpha_vantage", "ticker": instrument["ticker"]})
    provider = provider or AlphaVantage(store.settings.alpha_vantage_key)
    rows = provider.fetch(instrument)
    for article in rows:
        identity = article_id(article)
        store.add("news", article.model_dump(mode="json"), identity)
        store.add(
            "news_links",
            {"news_id": identity, "ticker": instrument["ticker"]},
            identity + "-" + instrument["ticker"],
        )
    return {"received": len(rows)}


def news_items(store):
    links = store.list("news_links", 20000)
    rows = store.list("news")
    for row in rows:
        row["tickers"] = sorted(
            set(row["tickers"]) | {link["ticker"] for link in links if link["news_id"] == row["id"]}
        )
    return rows


def analyze_pending(store):
    if not store.settings.finbert_enabled:
        raise ValueError(
            "FinBERT ist deaktiviert; SI_FINBERT_ENABLED=true und optionale Pakete erforderlich"
        )
    count = 0
    known = {s["news_id"] for s in store.list("sentiments")}
    for item in store.list("news"):
        if item["id"] not in known:
            result = analyze(item, store.settings.finbert_device)
            if result:
                store.add("sentiments", result, item["id"])
                count += 1
    return {"analyzed": count}
