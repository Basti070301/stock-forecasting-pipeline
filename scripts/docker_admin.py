"""Run explicit maintenance in an ephemeral backend container; no secrets in argv/logs."""

import argparse
import os
import subprocess
from pathlib import Path


def load_environment(path):
    # configure_docker.py generates plain KEY=value entries, no interpolation/shell code.
    result = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def maintenance(command, env_file=".env.docker", capture=False):
    values = load_environment(env_file)
    # Explicit file wins over ambient Compose variables, including project identity.
    environment = {**os.environ, **values}
    args = [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "--project-name",
        values["COMPOSE_PROJECT_NAME"],
        "-f",
        "compose.yaml",
    ]
    preview = values.get("SI_DEPLOYMENT_PROFILE") == "historical-preview"
    if preview:
        if not values["COMPOSE_PROJECT_NAME"].startswith("stockintelligence-m43-test") or values.get("SI_BIND_IP") != "127.0.0.1":
            raise ValueError("Preview-Wartung nur im eigenen Loopback-Testprojekt")
        args += ["-f", "compose.preview.yaml"]
    if command in {"prepare-research", "replay-research", "seed-reports", "verify-preview"} and not preview:
        raise ValueError("Dieser Befehl benötigt das explizite historische Preview-Profil")
    args += ["run",
        "--rm",
        "--no-deps",
        "-T",
    ]
    if command in {"init-db", "import-reference", "analyze-news", "replay-research", "seed-reports", "verify-preview"}:
        environment["DB_ADMIN_PASSWORD"] = values["SI_DB_ADMIN_PASSWORD"]
        args += ["-e", "DB_ADMIN_PASSWORD"]
    if command == "download-model":
        args += ["-e", "HF_HUB_OFFLINE=0"]
    args += ["si-backend", "python", "-m", "src.platform.maintenance", command]
    result = subprocess.run(
        args, env=environment, check=False, capture_output=capture, text=capture
    )
    return result if capture else result.returncode


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "init-db",
            "import-reference",
            "download-model",
            "check-model",
            "check-writes",
            "analyze-news",
            "prepare-research",
            "replay-research",
            "seed-reports",
            "verify-preview",
        ],
    )
    parser.add_argument("--env-file", default=".env.docker")
    args = parser.parse_args()
    raise SystemExit(maintenance(args.command, args.env_file))
