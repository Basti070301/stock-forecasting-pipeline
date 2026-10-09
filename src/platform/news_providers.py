"""Bounded official API/RSS adapters. No page scraping, payload logs or fallback stories."""

import ipaddress
import logging
import re
import socket
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import parse_qsl, urlsplit
from xml.etree import ElementTree

import httpx
from langdetect import detect_langs

from .news import Article, parse_alpha_payload

US_SYMBOLS = {"AAPL": "AAPL", "MSFT": "MSFT", "NVDA": "NVDA"}
ALIASES = {
    "AAPL": (r"\bApple\s+Inc\.?\b",),
    "MSFT": (r"\bMicrosoft(?:\s+Corporation)?\b",),
    "NVDA": (r"\bNVIDIA(?:\s+Corporation)?\b",),
    "SAP.DE": (r"\bSAP\s+SE\b",),
    "ALV.DE": (r"\bAllianz(?:\s+SE)?\b",),
}


class RedactQueryKeys(logging.Filter):
    def filter(self, record):
        record.msg = re.sub(
            r"(?i)([?&](?:apikey|api_key|token)=)[^&\s\"']+", r"\1[REDACTED]", record.getMessage()
        )
        record.args = ()
        return True


logging.getLogger("httpx").addFilter(RedactQueryKeys())


class ProviderError(ValueError):
    def __init__(self, code, message, cooldown=60):
        super().__init__(message)
        self.code, self.cooldown = code, cooldown


def plain(value, limit=1000):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]*>", " ", str(value or "")))).strip()[:limit]


def language_of(text):
    try:
        choices = detect_langs(text)
        return choices[0].lang if choices and choices[0].prob >= 0.9 else "unknown"
    except Exception:
        return "unknown"


def map_companies(symbols=(), text="", issuer=None):
    evidence = []
    for ticker, symbol in US_SYMBOLS.items():
        if symbol in symbols:
            evidence.append({"ticker": ticker, "method": "provider_ticker", "matched": symbol})
    if issuer:
        evidence.append({"ticker": issuer, "method": "approved_issuer_feed", "matched": issuer})
    for ticker, aliases in ALIASES.items():
        if any(e["ticker"] == ticker for e in evidence):
            continue
        for alias in aliases:
            matched = re.search(alias, text, flags=re.I)
            if matched:
                evidence.append(
                    {
                        "ticker": ticker,
                        "method": "controlled_company_alias",
                        "matched": matched.group(),
                    }
                )
                break
    return evidence


class HTTPProvider:
    def __init__(self, client=None, before_request=None, sleep=time.sleep):
        self.client = client
        self.before_request = before_request or (lambda: None)
        self.sleep = sleep

    def request(self, url, params=None, headers=None):
        def read(client):
            with client.stream(
                "GET", url, params=params, headers=headers, timeout=20, follow_redirects=False
            ) as stream:
                content = bytearray()
                if stream.status_code == 200:
                    for chunk in stream.iter_bytes():
                        content.extend(chunk)
                        if len(content) > 2 * 1024 * 1024:
                            raise ProviderError("oversize", "Provider-Antwort überschreitet 2 MiB")
                safe_headers = {
                    key: value
                    for key, value in stream.headers.items()
                    if key.lower() not in {"content-encoding", "content-length"}
                }
                return httpx.Response(
                    stream.status_code,
                    headers=safe_headers,
                    content=bytes(content),
                    request=stream.request,
                )

        for attempt in range(3):
            self.before_request()
            try:
                if self.client:
                    response = read(self.client)
                else:
                    with httpx.Client(timeout=20, follow_redirects=False) as client:
                        response = read(client)
                if response.status_code == 429:
                    retry = response.headers.get("Retry-After", "60")
                    try:
                        seconds = int(retry)
                    except ValueError:
                        try:
                            seconds = int(
                                (
                                    parsedate_to_datetime(retry) - datetime.now(timezone.utc)
                                ).total_seconds()
                            )
                        except Exception:
                            seconds = 60
                    raise ProviderError(
                        "rate_limit",
                        "Provider-Rate-Limit; später erneut abrufen",
                        max(60, min(seconds, 86400)),
                    )
                if response.status_code >= 500:
                    if attempt < 2:
                        self.sleep(2**attempt)
                        continue
                    raise ProviderError("http_5xx", "Provider vorübergehend nicht verfügbar")
                if response.status_code != 200:
                    raise ProviderError(
                        "http_error", f"Provider antwortet mit HTTP {response.status_code}"
                    )
                if len(response.content) > 2 * 1024 * 1024:
                    raise ProviderError("oversize", "Provider-Antwort überschreitet 2 MiB")
                return response
            except httpx.TransportError:
                if attempt == 2:
                    raise ProviderError(
                        "transport", "News-Provider: Timeout oder Netzwerkfehler"
                    ) from None
                self.sleep(2**attempt)
        raise ProviderError("transport", "News-Provider nicht erreichbar")


class Finnhub(HTTPProvider):
    name = "finnhub"

    def __init__(self, key, summaries=False, **kwargs):
        super().__init__(**kwargs)
        self.key, self.summaries = key, summaries

    def fetch(self, instrument):
        if not self.key:
            raise ProviderError("missing_key", "Finnhub: API-Schlüssel fehlt")
        symbol = US_SYMBOLS.get(instrument["ticker"])
        if not symbol:
            raise ProviderError(
                "unsupported_ticker",
                "Finnhub Company News unterstützt hier nur bestätigte US-Ticker",
            )
        now = datetime.now(timezone.utc)
        response = self.request(
            "https://api.finnhub.io/api/v1/company-news",
            params={
                "symbol": symbol,
                "from": (now - timedelta(days=30)).date().isoformat(),
                "to": now.date().isoformat(),
            },
            headers={"X-Finnhub-Token": self.key},
        )
        try:
            payload = response.json()
        except ValueError:
            raise ProviderError("invalid_json", "Finnhub: ungültiges JSON") from None
        if not isinstance(payload, list):
            raise ProviderError("invalid_payload", "Finnhub: keine gültige Nachrichtenliste")
        seen = datetime.now(timezone.utc)
        rows = []
        for item in payload[:250]:
            try:
                title = plain(item["headline"])
                description = plain(item.get("summary"), 800) if self.summaries else ""
                symbols = [s.strip() for s in str(item.get("related") or symbol).split(",")]
                evidence = map_companies(symbols, title + " " + description)
                if not evidence:
                    continue
                rows.append(
                    Article(
                        source=plain(item["source"], 200),
                        title=title,
                        description=description,
                        url=item["url"],
                        published_at=datetime.fromtimestamp(float(item["datetime"]), timezone.utc),
                        first_seen_at=seen,
                        last_updated_at=seen,
                        tickers=sorted({e["ticker"] for e in evidence}),
                        language=language_of(title + " " + description),
                        mapping_evidence=evidence,
                        provider=self.name,
                        provider_id=str(item.get("id", "")),
                    )
                )
            except (ValueError, KeyError, TypeError, OverflowError, OSError):
                logging.warning("news_record_rejected provider=finnhub reason=invalid_metadata")
        return rows


class ApprovedRSS(HTTPProvider):
    name = "rss"

    def __init__(self, feed, **kwargs):
        super().__init__(**kwargs)
        self.feed = feed
        parsed = urlsplit(feed.get("url", ""))
        if any(
            key.lower() in {"apikey", "api_key", "token", "password", "secret"}
            for key, _ in parse_qsl(parsed.query)
        ):
            raise ProviderError("invalid_feed", "RSS-URLs dürfen keine Zugangsdaten enthalten")
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
        ):
            raise ProviderError(
                "invalid_feed", "RSS verlangt eine öffentliche HTTPS-URL ohne Zugangsdaten"
            )
        if feed.get("rights_confirmed") is not True or not feed.get("license_reference"):
            raise ProviderError(
                "rights_missing", "RSS: ausdrückliche Speicher-/Analyseberechtigung fehlt"
            )
        if parsed.hostname in {"localhost"} or parsed.hostname.endswith((".local", ".internal")):
            raise ProviderError("invalid_feed", "Private Feed-Adressen sind nicht erlaubt")
        try:
            if not ipaddress.ip_address(parsed.hostname).is_global:
                raise ProviderError("invalid_feed", "Private Feed-Adressen sind nicht erlaubt")
        except ValueError as error:
            if isinstance(error, ProviderError):
                raise

    def fetch(self, instrument):
        if not self.client:
            host = urlsplit(self.feed["url"]).hostname
            try:
                addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
                if not addresses or any(
                    not ipaddress.ip_address(item[4][0]).is_global for item in addresses
                ):
                    raise ProviderError(
                        "invalid_feed", "RSS-Host darf nicht auf private Adressen zeigen"
                    )
            except socket.gaierror:
                raise ProviderError("dns", "RSS-Host nicht auflösbar") from None
        response = self.request(
            self.feed["url"], headers={"User-Agent": "StockIntelligenceAI/1.0 personal-news-reader"}
        )
        data = response.content
        if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper() or b"\x00" in data:
            raise ProviderError(
                "unsafe_xml", "RSS: DTD/Entities oder nicht unterstützte XML-Kodierung"
            )
        try:
            root = ElementTree.fromstring(data)
        except ElementTree.ParseError:
            raise ProviderError("invalid_xml", "RSS: ungültiges XML") from None
        entries = root.findall("./channel/item") or root.findall(
            "{http://www.w3.org/2005/Atom}entry"
        )
        if not entries and root.tag not in {"rss", "{http://www.w3.org/2005/Atom}feed"}:
            raise ProviderError("invalid_xml", "Antwort ist kein RSS-/Atom-Feed")
        seen = datetime.now(timezone.utc)
        result = []
        for item in entries[:100]:

            def value(name):
                element = item.find(name)
                if element is None:
                    element = item.find("{http://www.w3.org/2005/Atom}" + name)
                return element.text or "" if element is not None else ""

            try:
                title = plain(value("title"))
                raw_time = value("pubDate") or value("published")
                try:
                    published = parsedate_to_datetime(raw_time)
                except (ValueError, TypeError):
                    published = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
                link = value("link")
                if not link:
                    link_element = item.find("{http://www.w3.org/2005/Atom}link")
                    link = link_element.get("href", "") if link_element is not None else ""
                evidence = map_companies(text=title, issuer=self.feed.get("ticker"))
                if not evidence:
                    continue
                result.append(
                    Article(
                        source=self.feed["name"],
                        title=title,
                        url=link,
                        description="",
                        published_at=published,
                        first_seen_at=seen,
                        last_updated_at=seen,
                        tickers=sorted({e["ticker"] for e in evidence}),
                        mapping_evidence=evidence,
                        language=language_of(title),
                        provider="rss",
                        provider_id=value("guid") or value("id"),
                    )
                )
            except (ValueError, KeyError, TypeError):
                logging.warning("news_record_rejected provider=rss reason=invalid_metadata")
        return result


class LicensedAlphaVantage(HTTPProvider):
    name = "alpha_vantage"

    def __init__(self, key, summaries=False, **kwargs):
        super().__init__(**kwargs)
        self.key, self.summaries = key, summaries

    def fetch(self, instrument):
        if instrument["ticker"] not in US_SYMBOLS:
            raise ProviderError(
                "unsupported_ticker", "Alpha Vantage: keine bestätigte europäische Zuordnung"
            )
        if not self.key:
            raise ProviderError("missing_key", "Alpha Vantage: API-Schlüssel fehlt")
        response = self.request(
            "https://www.alphavantage.co/query",
            params={
                "function": "NEWS_SENTIMENT",
                "tickers": US_SYMBOLS[instrument["ticker"]],
                "sort": "LATEST",
                "limit": 50,
                "apikey": self.key,
            },
        )
        try:
            payload = response.json()
        except ValueError:
            raise ProviderError("invalid_json", "Alpha Vantage: ungültiges JSON") from None
        rows = parse_alpha_payload(
            payload, {**instrument, "news_symbol": US_SYMBOLS[instrument["ticker"]]}
        )
        for row in rows:
            row.mapping_evidence = [
                {
                    "ticker": instrument["ticker"],
                    "method": "provider_ticker",
                    "matched": US_SYMBOLS[instrument["ticker"]],
                }
            ]
            if not self.summaries:
                row.description = ""
                row.language = language_of(row.title)
            else:
                row.description = plain(row.description, 800)
            row.last_updated_at = row.first_seen_at
        return rows
