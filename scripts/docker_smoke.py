"""Explicit isolated local integration test; retains all volumes and never touches other projects."""

import argparse
import base64
import json
import os
import ssl
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from docker_admin import load_environment, maintenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env.docker")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--cached-model", action="store_true", help="Nur vorhandenen FinBERT-Cache offline vor/nach Neuerstellung prüfen")
    parser.add_argument(
        "--model",
        action="store_true",
        help="Explicit ~440 MB model download and offline CPU inference",
    )
    args = parser.parse_args()
    values = load_environment(args.env_file)
    project = values.get("COMPOSE_PROJECT_NAME", "")
    preview = values.get("SI_DEPLOYMENT_PROFILE") == "historical-preview"
    if (
        not (project.startswith("stockintelligence-m22-test") or (preview and project.startswith("stockintelligence-m43-test")))
        or values["SI_BIND_IP"] != "127.0.0.1"
        or values["SI_PUBLIC_HOST"] not in {"127.0.0.1", "localhost"}
    ):
        parser.error("Nur eigenes markiertes M22-/M43-Testprojekt auf 127.0.0.1 erlaubt")
    environment = {**os.environ, **values}
    compose = [
        "docker",
        "compose",
        "--env-file",
        args.env_file,
        "--project-name",
        project,
        "-f",
        "compose.yaml",
    ]
    if preview:
        compose += ["-f", "compose.preview.yaml"]
        existing = subprocess.check_output([*compose,"ps","-q","--all"],env=environment,text=True).split()
        for identity in existing:
            label = subprocess.check_output(["docker","inspect","--format",'{{index .Config.Labels "org.stockintelligence.profile"}}',identity],env=environment,text=True).strip()
            if label != "historical-preview":
                parser.error("Projektname bereits von unmarkierten Containern belegt; Abbruch")

    def run(*arguments):
        subprocess.run([*compose, *arguments], env=environment, check=True)

    def admin(command):
        result = maintenance(command, args.env_file, capture=True)
        if result.returncode:
            print(result.stderr)
            raise RuntimeError(f"Wartung fehlgeschlagen: {command}")
        print(result.stdout)
        return json.loads(result.stdout)

    if args.build:
        run("-f", "compose.build.yaml", "build", "--pull")
    run("up", "-d", "--wait", "--wait-timeout", "120", "si-postgres")
    admin("init-db")
    admin("import-reference")
    assert admin("import-reference") == {"stocks": 0, "prices": 0, "features": 0}
    admin("check-writes")
    if preview:
        admin("seed-reports")
        admin("prepare-research")
        replay = admin("replay-research")
        assert len(replay["historical_replays"]) == 10
        repeated = admin("replay-research")
        assert all(r["reused"] for r in repeated["historical_replays"])
        persisted_before = admin("verify-preview")
    if args.model:
        admin("download-model")
    if args.model or args.cached_model:
        admin("check-model")
    run("up", "-d", "--wait", "--wait-timeout", "180")
    evidence = Path(".runtime/m43-docker" if preview else ".runtime/m22-docker")
    evidence.mkdir(parents=True, exist_ok=True)
    certificate = subprocess.check_output(
        [*compose, "exec", "-T", "si-frontend", "cat", "/var/lib/si-tls/server.crt"],
        env=environment,
    )
    (evidence / "server.crt").write_bytes(certificate)
    context = ssl.create_default_context(cafile=str(evidence / "server.crt"))
    url = f"https://{values['SI_PUBLIC_HOST']}:{values['SI_PORT']}"
    auth = base64.b64encode(
        f"{values['SI_AUTH_USER']}:{values['SI_AUTH_PASSWORD']}".encode()
    ).decode()

    def request(path, authenticated=True, method="GET"):
        req = urllib.request.Request(
            url + path,
            method=method,
            headers={"Authorization": "Basic " + auth} if authenticated else {},
        )
        try:
            with urllib.request.urlopen(req, context=context, timeout=60) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    assert request("/", False)[0] == 401
    assert request("/api/stocks", False)[0] == 401
    assert request("/")[0] == 200
    assert request("/api/ready")[0] == 200
    assert request("/api/news/analyze", method="POST")[0] == 403
    if preview:
        assert request("/api/forecasts/current", method="POST")[0] == 403
        assert request("/api/forecasts/research", method="POST")[0] == 403
        config = json.loads(request("/api/settings")[1])
        assert config["data_profile"] == "historical_preview" and not config["allow_mutations"]
        current = json.loads(request("/api/research/current/status")[1])
        assert current["prospective"]["T0"] is None and not current["scheduler"]["running"]
        forecasts = json.loads(request("/api/forecasts?kind=research_forecast")[1])["items"]
        assert len(forecasts) == 10 and all(f["mode"] == "historical_replay" and f["status"] == "research_only" for f in forecasts)
    assert request("/openapi.json")[0] == 404
    before = request("/api/stocks/AAPL/history?limit=5000")
    assert before[0] == 200 and len(json.loads(before[1])["data"]) > 1000
    stocks = request("/api/stocks")
    assert stocks[0] == 200 and len(json.loads(stocks[1])) == 5
    # Recreate rather than only restart: verifies named volumes and DNS refresh.
    run("up", "-d", "--force-recreate", "--wait", "--wait-timeout", "180")
    assert request("/api/stocks/AAPL/history?limit=5000") == before
    certificate_after = subprocess.check_output(
        [*compose, "exec", "-T", "si-frontend", "cat", "/var/lib/si-tls/server.crt"],
        env=environment,
    )
    assert certificate_after == certificate
    if preview:
        assert admin("verify-preview") == persisted_before
    if args.model or args.cached_model:
        admin("check-model")  # Offline cache must survive recreation.
    logs = subprocess.check_output(
        [*compose, "logs", "--no-color", "--tail", "200"], env=environment, text=True
    )
    (evidence / "container-logs.txt").write_text(logs, encoding="utf-8")
    assert "Traceback (most recent call last)" not in logs
    run("ps")
    print(
        "Docker smoke passed: HTTPS/auth, API, writes, reference data and recreation persistence."
    )
    print("Test stack remains running for browser checks; no volumes were removed.")


if __name__ == "__main__":
    main()
