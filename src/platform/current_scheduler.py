"""Reuse the bounded NewsScheduler lifecycle and the existing single Jobs executor."""

import threading

from .current_forecasts import CurrentForecastPipeline
from .forecast_contract import ForecastError
from .news_scheduler import NewsScheduler


class CurrentScheduler(NewsScheduler):
    def __init__(self, store, jobs, factory=CurrentForecastPipeline):
        super().__init__(store, jobs)
        self.factory = factory
        self.blocked_code = None
        self.submitted_jobs = []

    @property
    def max_cycles(self):
        return self.store.settings.current_max_cycles

    @property
    def interval_seconds(self):
        return self.store.settings.current_interval_seconds

    def start(self):
        if not self.store.settings.current_auto_refresh or self.jobs is None:
            return
        try:
            self.factory(self.store).gate()
        except ForecastError as error:
            self.blocked_code = error.code
            return
        self.thread = threading.Thread(
            target=self.run, name="current-research-scheduler", daemon=True
        )
        self.thread.start()

    def tick(self):
        if not self.store.settings.current_auto_refresh or self.jobs is None:
            return False
        try:
            pipeline = self.factory(self.store)
            pipeline.gate()
            tickers = []
            for ticker in pipeline.protocol["universe"]:
                try:
                    plan = pipeline.plan(ticker)
                    if pipeline.store.get("market_runs", plan["slot"]) is None:
                        attempts = [
                            r
                            for r in pipeline.store.all("market_runs")
                            if r.get("kind") == "current_attempt" and r.get("slot") == plan["slot"]
                        ]
                        if len(attempts) < self.store.settings.current_session_attempts:
                            tickers.append(ticker)
                except ForecastError:
                    continue
            if not tickers:
                return False
            submitted = self.jobs.submit(
                "current-scheduled", lambda: pipeline.job(tickers, refresh=True)
            )
            if isinstance(submitted, dict):
                self.submitted_jobs.append(submitted["job_id"])
            self.blocked_code = None
            return True
        except ForecastError as error:
            self.blocked_code = error.code
        except ValueError:
            self.blocked_code = "job_busy"
        return False
