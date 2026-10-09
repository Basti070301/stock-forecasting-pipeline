import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from .store import utcnow


class Jobs:
    def __init__(self, store):
        self.store = store
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="intelligence")
        self.lock = Lock()
        self.active = False
        for job in store.list("jobs"):
            if job["status"] in {"queued", "running"}:
                store.update(
                    "jobs",
                    job["id"],
                    {**job, "status": "interrupted", "error": "Server wurde neu gestartet"},
                )

    def submit(self, kind, function, with_progress=False):
        with self.lock:
            if self.active:
                raise ValueError("Ein Job läuft bereits; bitte Abschluss abwarten")
            self.active = True
            payload = {
                "kind": kind,
                "status": "queued",
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error": None,
                "steps": [],
            }
            try:
                identity = self.store.add("jobs", payload)
            except Exception:
                self.active = False
                raise

        def progress(name, status, rows=None):
            existing = next((step for step in payload["steps"] if step["name"] == name), None)
            if existing is None:
                existing = {"name": name, "started_at": utcnow()}
                payload["steps"].append(existing)
            existing.update(status=status, rows=rows, updated_at=utcnow())
            self.store.update("jobs", identity, payload)

        def run():
            try:
                payload.update(status="running", started_at=utcnow())
                self.store.update("jobs", identity, payload)
                payload.update(
                    result=function(progress) if with_progress else function(), status="succeeded"
                )
            except Exception as exc:
                # Do not serialize raw provider/DB exceptions: URLs can contain credentials.
                logging.error("Job %s failed (%s)", identity, type(exc).__name__)
                for step in payload["steps"]:
                    if step["status"] == "running":
                        step.update(status="failed", updated_at=utcnow())
                payload.update(
                    status="failed",
                    error=str(exc)
                    if isinstance(exc, ValueError)
                    else f"{type(exc).__name__}: Verarbeitung fehlgeschlagen; Konfiguration prüfen",
                )
            finally:
                payload["finished_at"] = utcnow()
                try:
                    self.store.update("jobs", identity, payload)
                finally:
                    with self.lock:
                        self.active = False

        self.pool.submit(run)
        return {"job_id": identity, "status": "queued"}

    def close(self):
        self.pool.shutdown(wait=True)
