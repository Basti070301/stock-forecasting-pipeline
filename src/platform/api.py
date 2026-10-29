import hmac
import json
from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import SQLAlchemyError

from src.config import PROJECT_ROOT

from .config import Instrument, Settings
from .current_forecasts import CurrentForecastPipeline
from .current_scheduler import CurrentScheduler
from .forecast_contract import ForecastError, utc, utc_now
from .jobs import Jobs
from .market import MarketService, records
from .news import analyze_pending
from .news_engine import NewsEngine, stamp
from .news_scheduler import NewsScheduler
from .prospective import current_status
from .research import BacktestRequest, evaluate
from .research_forecasts import ForecastRequest, ResearchForecastEngine
from .store import TABLES, Store


class NewsRequest(BaseModel):
    ticker: str | None = None


class CurrentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tickers: list[Literal["AAPL", "MSFT", "NVDA", "SAP.DE", "ALV.DE"]] = Field(
        default=["AAPL", "MSFT", "NVDA", "SAP.DE", "ALV.DE"], min_length=1, max_length=5
    )
    refresh: bool = Field(default=False, strict=True)


def create_app(settings=None, store=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        app.state.store = store or Store(settings)
        if settings.mode == "demo":
            app.state.store.migrate()
        elif "si_schema_versions" not in inspect(app.state.store.engine).get_table_names():
            raise RuntimeError("Zuerst python -m src.platform.store --migrate ausführen")
        if settings.news_enabled and not NewsEngine(app.state.store).schema_available():
            raise RuntimeError(
                "News-Schema fehlt; explizit python -m src.platform.store --migrate ausführen"
            )
        app.state.market = MarketService(app.state.store)
        app.state.jobs = Jobs(app.state.store) if settings.allow_mutations else None
        app.state.news_scheduler = NewsScheduler(app.state.store, app.state.jobs)
        app.state.news_scheduler.start()
        app.state.current_scheduler = CurrentScheduler(app.state.store, app.state.jobs)
        app.state.current_scheduler.start()
        yield
        app.state.current_scheduler.close()
        app.state.news_scheduler.close()
        if app.state.jobs is not None:
            app.state.jobs.close()
        if not store:
            app.state.store.engine.dispose()

    app = FastAPI(
        title="Stock Intelligence AI",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.api_docs_enabled else None,
        redoc_url="/redoc" if settings.api_docs_enabled else None,
        openapi_url="/openapi.json" if settings.api_docs_enabled else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-SI-Token"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return JSONResponse(
            status_code=503,
            content={"detail": "Datenbank nicht verfügbar. Verbindung und Migration prüfen."},
        )

    @app.exception_handler(ForecastError)
    async def forecast_error(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc), "code": exc.code})

    @app.middleware("http")
    async def response_headers(request, call_next):
        if settings.proxy_token and request.url.path not in {"/api/health", "/api/ready"}:
            if not hmac.compare_digest(
                request.headers.get("x-si-proxy-token", ""), settings.proxy_token
            ):
                return JSONResponse(
                    status_code=403, content={"detail": "Proxy-Anmeldung erforderlich"}
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    def state():
        return app.state.store

    def authorize(request: Request):
        if not settings.allow_mutations:
            raise HTTPException(403, "Serverbetrieb: Wartung nur über die CLI am Docker-Host")
        origin = request.headers.get("origin")
        if origin and origin not in settings.allowed_origins + [
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        ]:
            raise HTTPException(403, "Unzulässiger Ursprung")
        if settings.mutation_token:
            if not hmac.compare_digest(
                request.headers.get("x-si-token", ""), settings.mutation_token
            ):
                raise HTTPException(403, "Lokaler Zugriffsschlüssel erforderlich")
        elif request.client and request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            raise HTTPException(403, "Mutationen sind nur lokal erlaubt")

    def instrument(ticker):
        item = state().get("instruments", ticker)
        if item is None:
            raise HTTPException(404, "Aktie nicht in der Watchlist")
        return item

    def submit(kind, function, with_progress=False):
        try:
            return app.state.jobs.submit(kind, function, with_progress=with_progress)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/health")
    def health():
        return {"status": "ok", "mode": settings.mode, "version": "1.0.0"}

    @app.get("/api/ready")
    def ready():
        with state().engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            version = connection.execute(
                select(TABLES["schema_versions"].c.id).where(
                    TABLES["schema_versions"].c.id
                    == f"{settings.mode}:v{settings.required_schema_version}"
                )
            ).scalar_one_or_none()
        if version is None:
            raise HTTPException(503, "Schema-Migration fehlt")
        return {"status": "ready", "mode": settings.mode}

    @app.get("/api/settings")
    def configuration():
        return {
            "mode": settings.mode,
            "watchlist": state().instruments(),
            "token_required": bool(settings.mutation_token),
            "allow_mutations": settings.allow_mutations,
            "providers": [
                {
                    "name": "Yahoo Finance",
                    "status": "Historischer Repository-Snapshot"
                    if settings.mode == "demo"
                    else "Manueller Abruf verfügbar; keine Live-SLA",
                },
                {
                    "name": f"News · {settings.news_provider}",
                    "status": NewsEngine(state()).configured_reason()
                    or "Konfiguriert; tatsächlichen Abrufstatus unter News Intelligence prüfen",
                },
                {
                    "name": "FinBERT",
                    "status": "Aktiviert · expliziter Cache-Download im Docker-Betrieb"
                    if settings.finbert_enabled
                    else "Deaktiviert · optionale Installation",
                },
            ],
            "intraday": "Intraday-Prognose nicht verfügbar – geeignete Marktdaten fehlen.",
        }

    @app.post("/api/settings/watchlist", dependencies=[Depends(authorize)])
    def watchlist(item: Instrument):
        if item.yahoo_symbol != item.ticker:
            raise HTTPException(422, "Yahoo-Symbol muss derzeit dem Pipeline-Ticker entsprechen")
        if state().get("instruments", item.ticker):
            state().update("instruments", item.ticker, item.model_dump())
        else:
            if len(state().instruments()) >= 20:
                raise HTTPException(422, "Maximal 20 Titel für den lokalen Forschungsbetrieb")
            state().add("instruments", item.model_dump(), item.ticker)
        return item

    @app.get("/api/stocks")
    def stocks():
        return [app.state.market.detail(i) for i in state().instruments()]

    @app.get("/api/stocks/{ticker}")
    def stock(ticker: str):
        return app.state.market.detail(instrument(ticker))

    @app.get("/api/stocks/{ticker}/history")
    def history(
        ticker: str, interval: Literal["1d"] = "1d", limit: int = Query(252, ge=1, le=5000)
    ):
        instrument(ticker)
        return {
            "interval": interval,
            "adjusted": True,
            "data": records(app.state.market.prices(ticker).tail(limit)),
        }

    @app.get("/api/news")
    def news(ticker: str | None = None, days: int = Query(30, ge=1, le=3650)):
        if ticker:
            instrument(ticker)
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
        return [
            n
            for n in NewsEngine(state()).items()
            if (not ticker or ticker in n["tickers"]) and pd.Timestamp(n["published_at"]) >= cutoff
        ]

    @app.get("/api/news/feed")
    def news_feed(
        ticker: str | None = None,
        source: str | None = Query(None, max_length=200),
        provider: Literal["finnhub", "alpha_vantage", "rss"] | None = None,
        days: int = Query(30, ge=1, le=3650),
        sentiment: Literal["positive", "negative", "neutral", "unavailable"] | None = None,
        page: int = Query(1, ge=1, le=10000),
        page_size: int = Query(20, ge=1, le=100),
        as_of: str | None = Query(None, max_length=40),
    ):
        if ticker:
            instrument(ticker)
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        try:
            snapshot = stamp(as_of) if as_of else now
            if snapshot > now:
                raise ValueError("Zukünftiger Zeitpunkt")
        except ValueError:
            raise HTTPException(
                422, "as_of verlangt einen gültigen Zeitpunkt mit Zeitzone bis jetzt"
            ) from None
        engine = NewsEngine(state())
        rows = [
            n
            for n in engine.items(snapshot)
            if stamp(n["published_at"]) >= snapshot - timedelta(days=days)
            and (not ticker or ticker in n["tickers"])
            and (not source or n["source"] == source)
            and (not provider or n["provider"] == provider)
            and (
                not sentiment
                or (n["analysis"] and n["analysis"]["dominant"] == sentiment)
                or (sentiment == "unavailable" and not n["analysis"])
            )
        ]
        start = (page - 1) * page_size
        return {
            "items": rows[start : start + page_size],
            "total": len(rows),
            "page": page,
            "page_size": page_size,
            "as_of": snapshot.isoformat(),
            "sources": sorted({n["source"] for n in engine.items(snapshot)}),
            "data_state": "unavailable"
            if not rows
            else "historical_provider"
            if all(n["stale"] for n in rows)
            else "provider",
        }

    @app.get("/api/news/providers")
    def news_providers():
        result = NewsEngine(state()).statuses()
        result["scheduler"] = {
            "cycles": app.state.news_scheduler.cycles,
            "running": bool(
                app.state.news_scheduler.thread and app.state.news_scheduler.thread.is_alive()
            ),
        }
        return result

    @app.get("/api/news/summary")
    def news_summary():
        engine = NewsEngine(state())
        return {
            "items": [engine.aggregate(item["ticker"], 7) for item in state().instruments()],
            "latest": engine.items()[:5],
            "providers": engine.statuses(),
        }

    @app.get("/api/stocks/{ticker}/sentiment")
    def stock_sentiment(ticker: str, as_of: str | None = Query(None, max_length=40)):
        instrument(ticker)
        try:
            snapshot = stamp(as_of) if as_of else None
            if snapshot and snapshot > pd.Timestamp.now(tz="UTC").to_pydatetime():
                raise ValueError("Zukunft")
        except ValueError:
            raise HTTPException(422, "Ungültiger as_of-Zeitpunkt") from None
        engine = NewsEngine(state())
        return {
            "ticker": ticker,
            "windows": [engine.aggregate(ticker, days, snapshot) for days in (1, 7, 30)],
        }

    @app.get("/api/stocks/{ticker}/news")
    def stock_news(ticker: str):
        instrument(ticker)
        return news(ticker, 30)

    @app.get("/api/radar")
    def radar(
        region: Literal["USA", "Europa"] | None = None,
        exchange: str | None = None,
        sector: str | None = None,
        sentiment: Literal["positive", "negative", "missing"] | None = None,
        days: int = Query(7, ge=1, le=90),
        horizon: Literal["all", "next_day", "60m", "120m"] = "all",
        model: Literal["all", "logistic", "random_forest"] = "all",
    ):
        rows = app.state.market.radar(days)
        rows = [
            r
            for r in rows
            if (not region or r["region"] == region)
            and (not exchange or r["exchange"] == exchange)
            and (not sector or r["sector"] == sector)
        ]
        if sentiment:
            rows = [
                r
                for r in rows
                if (
                    r["news_sentiment"] is None
                    if sentiment == "missing"
                    else r["news_sentiment"] is not None
                    and (
                        r["news_sentiment"] > 0
                        if sentiment == "positive"
                        else r["news_sentiment"] < 0
                    )
                )
            ]
        unavailable = horizon != "all" or model != "all"
        return {
            "items": [] if unavailable else rows,
            "note": "Keine freigegebenen Prognosen für diesen Modell-/Horizontfilter"
            if unavailable
            else "Regelbasiertes Radar −100 bis +100. Fehlende Komponenten zählen 0; Gewichte werden nicht umverteilt. Keine Gewinnwahrscheinlichkeit.",
        }

    @app.get("/api/models")
    def models():
        reference = json.loads((PROJECT_ROOT / "reports" / "model_metrics.json").read_text())
        return [
            {
                "id": "legacy-logistic",
                "name": "Logistische Regression · PoC",
                "status": "research_only",
                "metrics": reference,
                "calibrated": False,
                "forecast_enabled": False,
                "warning": "Referenzbericht: Modell unter Mehrheitsreferenz. Mehrheitswert aus Testverteilung; keine handelbare Strategie.",
            },
            *state().list("models", 50),
        ]

    @app.get("/api/forecasts")
    def forecasts(
        ticker: str | None = None,
        limit: int = Query(50, ge=1, le=1000),
        kind: Literal["research_forecast"] | None = None,
    ):
        if ticker:
            instrument(ticker)
        now = utc(utc_now())
        outcomes = {}
        for outcome in state().all("outcomes"):
            # A future timestamp, including observation/computation, must never leak.
            if all(
                not outcome.get(key) or utc(outcome[key]) <= now
                for key in ("outcome_at", "observed_at", "calculated_at")
            ):
                outcomes[outcome["forecast_id"]] = outcome
        rows = [
            f
            for f in state().list("forecasts", 10000)
            if (not ticker or f["ticker"] == ticker)
            and (not kind or f.get("kind") == kind)
            and (not f.get("generated_at") or utc(f["generated_at"]) <= now)
        ]
        return {
            "items": [
                {
                    **f,
                    "outcome": outcomes.get(f["id"]),
                    "current_confirmation": state().get("market_runs", f["pipeline_slot"])
                    if f.get("pipeline_slot")
                    else None,
                }
                for f in rows[:limit]
            ],
            "status": "Keine Modelle freigegeben. Kalibrierte Backtestwerte bleiben Forschungsergebnisse.",
        }

    @app.get("/api/research/models")
    def research_models():
        return {
            "items": ResearchForecastEngine(state()).catalog(),
            "can_generate": settings.allow_mutations and settings.research_trust_local_artifacts,
            "note": "Explizite Artefaktwahl; nur Forschung. Current Research benötigt den getrennten kontrollierten Ablauf und bestätigte Datenabnahme.",
        }

    @app.get("/api/research/current/status")
    def current_research_status(ticker: str | None = None):
        if ticker:
            instrument(ticker)
            if ticker not in {"AAPL", "MSFT", "NVDA", "SAP.DE", "ALV.DE"}:
                raise HTTPException(404, "Aktie gehört nicht zum fixierten Forschungsuniversum")
        result = current_status(CurrentForecastPipeline(state()), ticker)
        scheduler = app.state.current_scheduler
        result["scheduler"] = {
            "running": bool(scheduler.thread and scheduler.thread.is_alive()),
            "cycles": scheduler.cycles,
            "blocked_code": scheduler.blocked_code,
        }
        return result

    @app.post("/api/forecasts/current", status_code=202, dependencies=[Depends(authorize)])
    def current_research_forecasts(body: CurrentRequest):
        pipeline = CurrentForecastPipeline(state())
        pipeline.gate()
        if len(set(body.tickers)) != len(body.tickers):
            raise HTTPException(422, "Doppelte Aktien nicht zulässig")
        return submit("current-research", lambda: pipeline.job(body.tickers, refresh=body.refresh))

    @app.get("/api/research/evaluations")
    def research_evaluations():
        return {
            "items": [
                b for b in state().all("backtests") if b.get("kind") == "frozen_holdout_comparison"
            ],
            "note": "Projektweit unangetasteter Holdout noch nicht nachgewiesen; unabhängige Abnahme offen.",
        }

    @app.post("/api/forecasts/research", status_code=202, dependencies=[Depends(authorize)])
    def research_forecast(body: ForecastRequest):
        engine = ResearchForecastEngine(state())
        prepared = engine.prepare(body)
        owner = engine.claim(body.identity())

        def run():
            try:
                return engine.run_prepared(body, prepared)
            finally:
                engine.release(body.identity(), owner)

        try:
            return submit("research_forecast", run)
        except Exception:
            engine.release(body.identity(), owner)
            raise

    @app.get("/api/backtests")
    def backtests():
        return [
            {k: v for k, v in b.items() if k != "predictions"}
            for b in state().list("backtests", 50)
            if b.get("kind") not in {"frozen_holdout_comparison", "current_pipeline_validation"}
        ]

    @app.get("/api/backtests/{identity}")
    def backtest(identity: str):
        item = state().get("backtests", identity)
        if not item:
            raise HTTPException(404, "Backtest nicht gefunden")
        return item

    @app.post("/api/backtests", status_code=202, dependencies=[Depends(authorize)])
    def start_backtest(body: BacktestRequest):
        instruments = {t: instrument(t) for t in body.tickers}

        def run():
            frames = [app.state.market.prices(t) for t in body.tickers]
            if any(f.empty for f in frames):
                raise ValueError("Historische Kurse fehlen für mindestens einen ausgewählten Titel")
            identity = str(uuid4())
            artifact_dir = settings.runtime_dir / settings.mode / "backtests" / identity
            result = evaluate(pd.concat(frames, ignore_index=True), instruments, body, artifact_dir)
            state().add("backtests", result, identity)
            state().add(
                "models",
                {
                    "name": body.model,
                    "status": "research_only",
                    "metrics": result["metrics"],
                    "model_version": result["model_version"],
                    "calibrated": True,
                    "forecast_enabled": False,
                    "backtest_id": identity,
                    "folds": result["folds"],
                    "calibration": result["calibration"],
                    "feature_importance": result["feature_importance"],
                    "warning": result["limitations"][0],
                },
            )
            return {"backtest_id": identity, "test_rows": result["test_rows"]}

        return submit("backtest", run)

    @app.post("/api/news/refresh", status_code=202, dependencies=[Depends(authorize)])
    def refresh_news(body: NewsRequest):
        engine = NewsEngine(state())
        if body.ticker:
            instrument(body.ticker)
        reason = engine.configured_reason()
        if reason:
            raise HTTPException(409, reason)
        if body.ticker and not any(body.ticker in covered for _, _, covered in engine.sources()):
            raise HTTPException(409, "Keine bestätigte Provider-Zuordnung für diese Aktie")
        return submit("news", lambda: NewsEngine(state()).refresh(body.ticker, strict=True))

    @app.post("/api/news/analyze", status_code=202, dependencies=[Depends(authorize)])
    def analyze_news():
        if not settings.finbert_enabled:
            raise HTTPException(409, "FinBERT ist nicht aktiviert")
        return submit("finbert", lambda: analyze_pending(state()))

    @app.post("/api/pipeline/refresh", status_code=202, dependencies=[Depends(authorize)])
    def refresh_prices():
        def run(progress):
            if settings.mode == "demo":
                progress("Repository-Snapshots validieren", "running")
                count = sum(
                    len(app.state.market.prices(i["ticker"])) for i in state().instruments()
                )
                progress("Repository-Snapshots validieren", "succeeded", count)
                return {
                    "steps": [{"name": "Repository-Snapshots validiert", "status": "succeeded"}],
                    "rows": count,
                }
            from src.database import initialize_database
            from src.feature_engineering import build_features
            from src.ingestion import run_ingestion
            from src.preprocessing import process_ticker

            tickers = [i["ticker"] for i in state().instruments()]
            progress("Yahoo-Ingestion", "running")
            results = run_ingestion(tickers, "5y")
            if any(v != "ok" for v in results.values()):
                raise ValueError(
                    "Yahoo-Abruf teilweise fehlgeschlagen; Raw-Snapshots prüfen und erneut starten"
                )
            progress("Yahoo-Ingestion", "succeeded")
            progress("Preprocessing + Upserts", "running")
            initialize_database(state().engine)
            count = 0
            for ticker in tickers:
                count += len(process_ticker(ticker, engine=state().engine, replace_existing=False))
            progress("Preprocessing + Upserts", "succeeded", count)
            progress("Features + Upserts", "running")
            features = build_features(engine=state().engine, replace_existing=False)
            progress("Features + Upserts", "succeeded", len(features))
            return {
                "rows": count,
                "feature_rows": len(features),
                "steps": [
                    {"name": s, "status": "succeeded"}
                    for s in ["Yahoo-Ingestion", "Preprocessing + Upserts", "Features + Upserts"]
                ],
            }

        return submit("pipeline", run, with_progress=True)

    @app.get("/api/pipeline/status")
    def pipeline_status():
        jobs = state().list("jobs", 100)
        successful = next(
            (j for j in jobs if j["status"] == "succeeded" and j["kind"] == "pipeline"), None
        )
        return {
            "jobs": jobs,
            "last_success": successful,
            "source_snapshot": "2026-08-25T21:30:28Z" if settings.mode == "demo" else None,
            "mode": settings.mode,
        }

    @app.get("/api/jobs/{identity}")
    def job(identity: str):
        item = state().get("jobs", identity)
        if not item:
            raise HTTPException(404, "Job nicht gefunden")
        return item

    dist = PROJECT_ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        def index():
            return FileResponse(dist / "index.html")

    return app


app = create_app()
