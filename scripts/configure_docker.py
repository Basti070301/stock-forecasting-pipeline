"""Generate private deployment configuration without printing secrets or overwriting files."""

import argparse
import ipaddress
import os
import re
import secrets
from pathlib import Path


def private_bind(value):
    address = ipaddress.IPv4Address(value)
    networks = ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10")
    if not any(address in ipaddress.ip_network(net) for net in networks):
        raise ValueError("Nur Loopback, RFC1918 oder Tailscale-IPv4 als Bind-Adresse erlaubt")
    return str(address)


def generate(path, bind="127.0.0.1", port=8085, host=None, project="stockintelligence"):
    bind = private_bind(bind)
    host = host or bind
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host):
        raise ValueError("Host muss eine IPv4 oder ein kleingeschriebener DNS-Name sein")
    if not 1024 <= port <= 65535 or not re.fullmatch(r"[a-z][a-z0-9_-]{0,40}", project):
        raise ValueError("Ungültiger Port oder Projektname")
    values = {
        "COMPOSE_PROJECT_NAME": project,
        "SI_BIND_IP": bind,
        "SI_PUBLIC_HOST": host,
        "SI_PORT": port,
        "SI_AUTH_USER": "research",
        **{
            key: secrets.token_hex(24)
            for key in (
                "SI_AUTH_PASSWORD",
                "SI_PROXY_TOKEN",
                "SI_DB_ADMIN_PASSWORD",
                "SI_DB_APP_PASSWORD",
            )
        },
        "SI_FRONTEND_IMAGE": "stockintelligence-frontend:m22",
        "SI_BACKEND_IMAGE": "stockintelligence-backend:m22",
        "SI_BACKEND_MEMORY": "4g",
        "SI_BACKEND_CPUS": "2.0",
        "SI_DB_MEMORY": "1g",
        "SI_ALPHA_VANTAGE_KEY": "",
    }
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("# Private deployment configuration. Do not commit or share.\n")
        stream.writelines(f"{key}={value}\n" for key, value in values.items())
    return f"https://{host}:{port}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".env.docker"))
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int, default=8085)
    parser.add_argument("--project", default="stockintelligence")
    args = parser.parse_args()
    try:
        url = generate(args.output, args.bind, args.port, args.host, args.project)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Konfiguration nicht erstellt: {error}\n")
    print(f"Erstellt: {args.output}. Ziel: {url}. Kennwörter stehen nur in der Datei.")
