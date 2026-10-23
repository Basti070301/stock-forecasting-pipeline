"""Explicit local daily ingestion: python -m src.platform.market_data --help."""

import argparse
import json
import time
from datetime import date
from uuid import uuid4

import pandas as pd

from .config import Settings
from .forecast_contract import utc_now
from .market_data_provider import INSTRUMENTS, MarketDataError, YahooDailyProvider, checksum, stamp
from .market_data_store import MarketRepository
from .store import Store


class MarketIngestion:
    def __init__(self, repository, provider, clock=utc_now, sleep=time.sleep):
        self.repo, self.provider, self.clock, self.sleep = repository, provider, clock, sleep
        self.settings = repository.store.settings

    def _reserve(self, run_id, ticker):
        now = pd.Timestamp(self.clock())
        events = self.repo.store.all("market_runs")
        attempts = [r for r in events if r["kind"] == "attempt_start"]
        today = [r for r in attempts if pd.Timestamp(r["at"]).date() == now.date()]
        if len(today) >= self.settings.market_daily_budget:
            raise MarketDataError("budget", "Tagesbudget logischer Provideraufrufe erreicht")
        cooldowns = [pd.Timestamp(r["next_allowed_at"]) for r in events if r.get("next_allowed_at")]
        if cooldowns and max(cooldowns) > now:
            raise MarketDataError("cooldown", "Provider befindet sich noch in der Abrufpause")
        if attempts:
            elapsed = (now - max(pd.Timestamp(r["at"]) for r in attempts)).total_seconds()
            if elapsed < 0:
                raise MarketDataError(
                    "clock", "Lokale Uhr liegt vor dem zuletzt protokollierten Abruf"
                )
            wait = self.settings.market_min_interval_seconds - elapsed
            if wait > 0:
                self.sleep(min(wait, 60))
        # Reserve BEFORE the request: a crashed process still consumes its logical-call budget.
        return self.repo.event("attempt_start", run_id=run_id, ticker=ticker)

    def run(self, tickers, start, end):
        reason = self.provider.configured_reason()
        if reason:
            raise MarketDataError("access_blocked", reason)
        if (
            not tickers
            or len(set(tickers)) != len(tickers)
            or any(t not in INSTRUMENTS for t in tickers)
        ):
            raise MarketDataError(
                "request", "Eindeutige Auswahl der fünf unterstützten Aktien erforderlich"
            )
        if not start <= end or (end - start).days > 732:
            raise MarketDataError("request", "Ungültiger Tagesdatenbereich (maximal 733 Tage)")
        if not self.repo.migrated():
            raise MarketDataError("schema", "Additive Tagesdatenmigration fehlt")
        owner = self.repo.acquire()
        run_id, results = str(uuid4()), []
        try:
            self.repo.event(
                "run_start",
                run_id=run_id,
                tickers=tickers,
                requested_start=start.isoformat(),
                requested_end=end.isoformat(),
                rights_reference_sha256=checksum(self.settings.market_rights_reference),
            )
            for ticker in tickers:
                result = {"ticker": ticker, "status": "failed", "attempts": 0}
                for number in range(self.settings.market_max_attempts):
                    attempt_id = None
                    try:
                        attempt_id = self._reserve(run_id, ticker)
                        result["attempts"] += 1
                        receipt = self.provider.fetch(ticker, start, end)
                        if (
                            receipt.ticker != ticker
                            or receipt.requested_start != start
                            or receipt.requested_end != end
                        ):
                            raise MarketDataError(
                                "response_identity",
                                "Providerantwort stimmt nicht mit dem angeforderten Instrument/Zeitraum überein",
                            )
                        stored = self.repo.persist(receipt)
                        result.update(stored)
                        result.pop("error", None)
                        result["status"] = (
                            "success"
                            if stored["quality"]["status"] == "accepted"
                            else "quarantined"
                        )
                        self.repo.event(
                            "attempt_result",
                            attempt_id=attempt_id,
                            status=result["status"],
                            receipt_id=stored["receipt_id"],
                        )
                        break
                    except MarketDataError as error:
                        result["error"] = error.code
                        fields = {"attempt_id": attempt_id, "status": "failed", "error": error.code}
                        if error.code == "rate_limit":
                            fields["next_allowed_at"] = stamp(
                                pd.Timestamp(self.clock()) + pd.Timedelta(seconds=error.cooldown)
                            )
                        self.repo.event("attempt_result", **fields)
                        if not error.retryable or number + 1 == self.settings.market_max_attempts:
                            break
                        self.sleep(min(2**number, 8))
                results.append(result)
            status = (
                "success"
                if all(r["status"] == "success" for r in results)
                else "partial"
                if any(r["status"] == "success" for r in results)
                else "failed"
            )
            self.repo.event("run_end", run_id=run_id, status=status, results=results)
            return {"run_id": run_id, "provider": "yfinance", "status": status, "results": results}
        finally:
            self.repo.release(owner)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="Nur additive Plattform-/Tagesdatentabellen anlegen")
    sub.add_parser("status", help="Konfiguration prüfen, ohne Providerzugriff")
    fetch = sub.add_parser("ingest", help="Kontrollierter manueller Tagesdatenabruf")
    fetch.add_argument("--tickers", nargs="+", choices=list(INSTRUMENTS), default=list(INSTRUMENTS))
    fetch.add_argument("--start", type=date.fromisoformat, required=True)
    fetch.add_argument(
        "--end",
        type=date.fromisoformat,
        required=True,
        help="Inklusives börsenlokales Handelsdatum",
    )
    for command in ("history", "revisions"):
        view = sub.add_parser(command)
        view.add_argument("--ticker", choices=list(INSTRUMENTS), required=True)
        view.add_argument("--as-of", required=True, help="ISO-Zeitpunkt mit Zeitzone")
    args = parser.parse_args(argv)
    try:
        settings = Settings()
        store = Store(settings)
        repo, provider = MarketRepository(store), YahooDailyProvider(settings)
        if args.command == "migrate":
            if settings.mode == "demo":
                store.migrate()
            repo.migrate()
            output = {"status": "migrated", "schema": 4, "destructive_operations": False}
        elif args.command == "status":
            output = {
                "provider": provider.name,
                "database_mode": settings.mode,
                "migrated": repo.migrated(),
                "access": "blocked" if provider.configured_reason() else "configured_not_verified",
                "reason": provider.configured_reason(),
                "declared_delay_seconds": settings.market_delay_seconds,
                "automatic_jobs": False,
            }
        elif args.command == "ingest":
            output = MarketIngestion(repo, provider).run(args.tickers, args.start, args.end)
        else:
            if not repo.migrated():
                raise MarketDataError("schema", "Tagesdatenmigration fehlt")
            if args.command == "revisions":
                output = repo.revisions(args.ticker, stamp(args.as_of))
            else:
                frame, receipt = repo.history(args.ticker, stamp(args.as_of))
                output = {
                    "receipt_id": receipt["id"],
                    "received_at": receipt["received_at"],
                    "available_at": receipt["available_at"],
                    "source_kind": receipt["source_kind"],
                    "quality": receipt["quality"],
                    "bars": [
                        {**r, "trade_date": pd.Timestamp(r["trade_date"]).date().isoformat()}
                        for r in frame.to_dict("records")
                    ],
                }
        print(json.dumps(output, ensure_ascii=False, allow_nan=False))
        return (
            1 if isinstance(output, dict) and output.get("status") in {"partial", "failed"} else 0
        )
    except MarketDataError as error:
        print(
            json.dumps(
                {"status": "blocked", "code": error.code, "message": str(error)}, ensure_ascii=False
            )
        )
        return 1
    except Exception:
        # Never disclose database URLs, local credential values or provider error bodies.
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": "local_error",
                    "message": "Lokaler Konfigurations-/Speicherfehler; sichere Diagnose erforderlich",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
