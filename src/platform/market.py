import hashlib
import json
from datetime import datetime, timezone
from functools import lru_cache

import numpy as np
import pandas as pd
from sqlalchemy import text

from src.config import RAW_PRICE_DIR
from src.feature_engineering import FEATURE_COLUMNS, calculate_features
from src.preprocessing import clean_price_frame

SNAPSHOT = "20260825T213028Z"


@lru_cache(maxsize=20)
def demo_prices(ticker):
    path = RAW_PRICE_DIR / f"{ticker.replace('.', '_')}_{SNAPSHOT}.csv"
    if not path.exists():
        return pd.DataFrame()
    return clean_price_frame(pd.read_csv(path), ticker)


def records(frame):
    return json.loads(
        frame.replace([np.inf, -np.inf], np.nan).to_json(orient="records", date_format="iso")
    )


def digest(frame):
    return hashlib.sha256(frame.to_csv(index=False).encode()).hexdigest()


def session_close(day, calendar):
    import exchange_calendars as xcals

    cal = xcals.get_calendar(calendar)
    stamp = pd.Timestamp(day).normalize().tz_localize(None)
    if not cal.is_session(stamp):
        return None
    return cal.session_close(stamp).isoformat()


class MarketService:
    def __init__(self, store):
        self.store = store

    def prices(self, ticker):
        if self.store.settings.mode == "demo":
            return demo_prices(ticker).copy()
        with self.store.engine.connect() as conn:
            return pd.read_sql(
                text("""SELECT s.ticker, p.trade_date, p.open_price,
                p.high_price, p.low_price, p.close_price, p.volume
                FROM fact_stock_price p JOIN dim_stock s ON s.stock_id=p.stock_id
                WHERE s.ticker=:ticker ORDER BY p.trade_date"""),
                conn,
                params={"ticker": ticker},
            )

    def detail(self, instrument):
        ticker = instrument["ticker"]
        frame = self.prices(ticker)
        result = {
            **instrument,
            "price": None,
            "change": None,
            "as_of": None,
            "session_close_utc": None,
            "session_complete": None,
            "features": {},
            "volume": None,
            "relative_volume": None,
            "quality": {"rows": len(frame)},
            "intervals": ["1d"] if len(frame) else [],
            "source": "Yahoo Finance · Repository-Snapshot"
            if self.store.settings.mode == "demo"
            else "PostgreSQL · Yahoo Finance",
            "forecast_probability": None,
            "forecast_status": "Nicht freigegeben – keine unabhängig validierte Prognosestrategie",
            "intraday_status": "Intraday-Prognose nicht verfügbar – geeignete Marktdaten fehlen.",
        }
        if frame.empty:
            return result
        features = calculate_features(frame)
        last = frame.iloc[-1]
        result.update(
            price=float(last.close_price),
            volume=None if pd.isna(last.volume) else int(last.volume),
            as_of=str(last.trade_date),
            features=records(features.tail(1))[0],
        )
        result["change"] = result["features"].get("daily_return")
        closed_at = session_close(last.trade_date, instrument["calendar"])
        result["session_close_utc"] = closed_at
        result["session_complete"] = closed_at is not None and pd.Timestamp(
            closed_at
        ) <= pd.Timestamp.now(tz="UTC")
        reference = pd.to_numeric(frame.volume).shift(1).rolling(20, min_periods=20).mean().iloc[-1]
        result["relative_volume"] = (
            float(last.volume / reference)
            if pd.notna(reference) and reference > 0 and pd.notna(last.volume)
            else None
        )
        result["quality"]["missing_feature_values"] = int(
            features[FEATURE_COLUMNS].isna().sum().sum()
        )
        result["quality"]["missing_volume_rows"] = int(frame.volume.isna().sum())
        result["age_days"] = max(
            0, (datetime.now(timezone.utc).date() - pd.Timestamp(last.trade_date).date()).days
        )
        result["stale"] = result["age_days"] > 4
        return result

    def radar(self, days=7):
        from .news_engine import NewsEngine
        engine = NewsEngine(self.store)
        output = []
        for instrument in self.store.instruments():
            row = self.detail(instrument)
            summary = engine.aggregate(row["ticker"], days)
            sentiment = summary["mean_sentiment"]
            momentum = row["features"].get("momentum_7")
            if row["session_complete"] is False:
                momentum = None
            trend = None
            ma = row["features"].get("moving_average_30")
            if ma and row["price"] and row["session_complete"]:
                trend = row["price"] / ma - 1
            rv = row["relative_volume"]
            components = {
                "Nachrichten (40 %)": None if sentiment is None else 40 * sentiment,
                "Momentum 7 Sitzungen (30 %)": None
                if momentum is None
                else 30 * float(np.clip(momentum / 0.1, -1, 1)),
                "Relatives Volumen (15 %)": None
                if rv is None or momentum is None
                else 15 * float(np.clip(rv - 1, 0, 1)) * float(np.sign(momentum)),
                "Trend MA30 (15 %)": None
                if trend is None
                else 15 * float(np.clip(trend / 0.1, -1, 1)),
            }
            available = [v for v in components.values() if v is not None]
            row.update(
                news_sentiment=sentiment,
                news_count=summary["analyzed_count"],
                radar_score=round(sum(available), 1) if available else None,
                components=components,
                coverage=len(available),
                momentum=momentum,
            )
            output.append(row)
        return sorted(
            output,
            key=lambda r: r["radar_score"] if r["radar_score"] is not None else -1000,
            reverse=True,
        )
