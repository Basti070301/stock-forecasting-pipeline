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
    parser.add_argument(
        "--model",
        action="store_true",
        help="Explicit ~440 MB model download and offline CPU inference",
    )
    args = parser.parse_args()
    values = load_environment(args.env_file)
    project = values.get("COMPOSE_PROJECT_NAME", "")
    if (
        not project.startswith("stockintelligence-m22-test")
        or values["SI_BIND_IP"] != "127.0.0.1"
        or values["SI_PUBLIC_HOST"] not in {"127.0.0.1", "localhost"}
    ):
        parser.error("Nur eigenes stockintelligence-m22-test* Projekt auf 127.0.0.1 erlaubt")
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
    if args.model:
        admin("download-model")
        admin("check-model")
    run("up", "-d", "--wait", "--wait-timeout", "180")
    evidence = Path(".runtime/m22-docker")
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
    if args.model:
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
