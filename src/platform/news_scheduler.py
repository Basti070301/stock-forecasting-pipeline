"""Optional bounded scheduler on the existing job executor; no new infrastructure."""

import threading

from .news_engine import NewsEngine


class NewsScheduler:
    def __init__(self, store, jobs):
        self.store, self.jobs = store, jobs
        self.stop_event = threading.Event()
        self.cycles = 0
        self.thread = None

    def start(self):
        settings = self.store.settings
        if not (settings.news_auto_refresh and settings.news_enabled and settings.allow_mutations):
            return
        if (
            NewsEngine(self.store).configured_reason()
            or not NewsEngine(self.store).schema_available()
        ):
            return
        self.thread = threading.Thread(target=self.run, name="news-scheduler", daemon=True)
        self.thread.start()

    def tick(self):
        try:
            self.jobs.submit("news-scheduled", lambda: NewsEngine(self.store).refresh(strict=True))
        except ValueError:
            return False
        return True

    def run(self):
        settings = self.store.settings
        for cycle in range(settings.news_max_cycles):
            if self.stop_event.is_set():
                break
            self.tick()
            self.cycles += 1
            if cycle + 1 < settings.news_max_cycles and self.stop_event.wait(
                settings.news_interval_seconds
            ):
                break

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)


def main():
    import argparse
    import json
    import time

    from .config import Settings
    from .store import Store

    parser = argparse.ArgumentParser(description="Kontrollierter News-Abruf ohne Browser/Docker")
    parser.add_argument("command", choices=["refresh", "analyze", "status", "schedule"])
    parser.add_argument("--ticker")
    parser.add_argument("--cycles", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.cycles <= 288:
        parser.error("cycles muss zwischen 1 und 288 liegen")
    settings = Settings()
    store = Store(settings)
    if settings.mode == "demo":
        store.migrate()
    try:
        engine = NewsEngine(store)
        if args.command == "status":
            print(json.dumps(engine.statuses(), indent=2))
        elif args.command == "analyze":
            print(json.dumps(engine.analyze(), indent=2))
        else:
            for cycle in range(args.cycles if args.command == "schedule" else 1):
                result = engine.refresh(args.ticker)
                print(json.dumps(result, indent=2))
                if result["errors"]:
                    return 1
                if args.command == "schedule" and cycle + 1 < args.cycles:
                    time.sleep(settings.news_interval_seconds)
        return 0
    except ValueError as error:
        print(json.dumps({"error": str(error)}))
        return 1
    except Exception:
        print(
            json.dumps(
                {"error": "News-Verarbeitung fehlgeschlagen; Konfiguration/Migration prüfen"}
            )
        )
        return 1
    finally:
        store.engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
