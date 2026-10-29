"""Explicit local commands, no automatic migration, activation or public acceptance endpoint."""

import argparse
import json

from .config import Settings
from .current_forecasts import CurrentForecastPipeline
from .jobs import Jobs
from .prospective import current_status
from .store import Store


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser(
        "verify",
        help="Lokale Inferenz-/Persistenzprüfung echter gespeicherter Daten, keine Forecast-Kohorte",
    )
    accept = sub.add_parser(
        "accept", help="Ausdrückliche Betreiberbestätigung nach echter E2E-Abnahme"
    )
    accept.add_argument("--validation-id", required=True)
    accept.add_argument(
        "--evidence-reference",
        required=True,
        help="Nicht geheime lokale Referenz auf manuelle API-/Browser-Prüfung",
    )
    accept.add_argument("--confirm-e2e", action="store_true", required=True)
    run = sub.add_parser("run")
    run.add_argument("--tickers", nargs="+", choices=["AAPL", "MSFT", "NVDA", "SAP.DE", "ALV.DE"])
    run.add_argument(
        "--refresh",
        action="store_true",
        help="Zusätzlich kontrolliert echte Kurse abrufen (nur nach Abnahme)",
    )
    schedule = sub.add_parser("schedule")
    schedule.add_argument("--cycles", type=int, default=1)
    args = parser.parse_args(argv)
    store, jobs = None, None
    try:
        settings = Settings()
        store = Store(settings)
        pipeline = CurrentForecastPipeline(store)
        if args.command == "status":
            output = current_status(pipeline)
        elif args.command == "verify":
            output = pipeline.verify()
        elif args.command == "accept":
            output = pipeline.accept(args.validation_id, args.evidence_reference)
        elif args.command == "run":
            output = pipeline.run(args.tickers, refresh=args.refresh)
        else:
            from .current_scheduler import CurrentScheduler

            if not 1 <= args.cycles <= min(288, settings.current_max_cycles):
                raise ValueError("cycles muss innerhalb des konfigurierten Limits liegen")
            if not settings.current_auto_refresh:
                raise ValueError(
                    "Scheduler ist standardmäßig deaktiviert; explizite Konfiguration fehlt"
                )
            pipeline.gate()
            jobs = Jobs(store)
            scheduler = CurrentScheduler(store, jobs)
            # Bound even an explicit CLI process; keep its own stop lifecycle.
            settings.current_max_cycles = args.cycles
            try:
                scheduler.run()
            finally:
                scheduler.close()
            jobs.close()
            jobs = None
            history = [store.get("jobs", identity) for identity in scheduler.submitted_jobs]
            state = (
                "blocked"
                if any(j["status"] != "succeeded" for j in history)
                else "partial"
                if any(j.get("result", {}).get("partial") for j in history)
                else "completed"
                if history
                else "idle"
            )
            output = {
                "status": state,
                "cycles": scheduler.cycles,
                "blocked_code": scheduler.blocked_code,
                "jobs": [
                    {"job_id": j["id"], "status": j["status"], "error": j["error"]} for j in history
                ],
            }
        print(json.dumps(output, ensure_ascii=False, allow_nan=False))
        return (
            1 if isinstance(output, dict) and output.get("status") in {"partial", "blocked"} else 0
        )
    except ValueError as error:
        # All expected errors are internal bounded messages, never raw provider errors.
        from .forecast_contract import ForecastError

        safe = (
            str(error)
            if isinstance(error, ForecastError)
            else "Lokale Konfiguration/Parameter prüfen"
        )
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "code": getattr(error, "code", "configuration"),
                    "message": safe,
                }
            )
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "message": "Lokaler Current-Job fehlgeschlagen; sichere Diagnose erforderlich",
                }
            )
        )
        return 1
    finally:
        if jobs:
            jobs.close()
        if store:
            store.engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
