import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from scripts.configure_docker import generate, private_bind
from scripts.docker_admin import maintenance
from src.platform.api import create_app
from src.platform.config import Settings
from src.platform.news import FINBERT_REVISION, finbert_options
from src.platform.store import Store


def test_private_configuration_and_no_overwrite(tmp_path):
    for ip in ("0.0.0.0", "8.8.8.8", "169.254.1.1", "224.0.0.1", "::"):
        with pytest.raises(ValueError):
            private_bind(ip)
    for ip in ("127.0.0.1", "192.168.10.8", "10.1.2.3", "100.90.80.70"):
        assert private_bind(ip) == ip
    path = tmp_path / ".env.docker"
    assert generate(path) == "https://127.0.0.1:8085"
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        generate(path)
    assert path.read_bytes() == original
    values = dict(
        line.split("=", 1) for line in original.decode().splitlines() if not line.startswith("#")
    )
    assert len(values["SI_AUTH_PASSWORD"]) >= 32
    assert values["SI_DB_APP_PASSWORD"] != values["SI_DB_ADMIN_PASSWORD"]


def test_server_auth_hosts_readiness_and_mutation_block(tmp_path):
    settings = Settings(
        runtime_dir=tmp_path,
        mode="demo",
        allow_mutations=False,
        api_docs_enabled=False,
        proxy_token="secret-proxy-test",
        allowed_hosts=["testserver"],
        allowed_origins=["https://testserver"],
    )
    store = Store(settings)
    with TestClient(create_app(settings, store)) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/ready").status_code == 200
        assert client.get("/api/stocks").status_code == 403
        headers = {"X-SI-Proxy-Token": "secret-proxy-test"}
        assert client.get("/api/stocks", headers=headers).status_code == 200
        assert (
            client.get("/api/settings", headers={**headers, "Host": "attacker.invalid"}).status_code
            == 400
        )
        assert (
            client.post(
                "/api/news/analyze", headers={**headers, "X-Forwarded-For": "127.0.0.1"}
            ).status_code
            == 403
        )
        assert client.get("/openapi.json", headers=headers).status_code == 404
        response = client.get("/api/stocks", headers={**headers, "Origin": "https://evil.invalid"})
        assert "access-control-allow-origin" not in response.headers
        with store.engine.begin() as conn:
            conn.execute(text("DELETE FROM si_schema_versions"))
        assert client.get("/api/ready").status_code == 503
    store.engine.dispose()


def test_finbert_cache_and_pinned_offline_revision(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    options = finbert_options()
    assert options["cache_dir"] == tmp_path / "hub"
    assert options["local_files_only"] is True
    assert options["revision"] == FINBERT_REVISION
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "custom"))
    assert finbert_options()["cache_dir"] == tmp_path / "custom"


def test_maintenance_pins_project_and_does_not_expose_admin_secret(monkeypatch, tmp_path):
    from types import SimpleNamespace

    path = tmp_path / ".env.docker"
    generate(path, project="stockintelligence-m22-test-unit")
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "unrelated-production-stack")
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("scripts.docker_admin.subprocess.run", run)
    assert maintenance("init-db", path) == 0
    args, kwargs = calls[-1]
    assert args[args.index("--project-name") + 1] == "stockintelligence-m22-test-unit"
    assert kwargs["env"]["COMPOSE_PROJECT_NAME"] == "stockintelligence-m22-test-unit"
    assert kwargs["env"]["DB_ADMIN_PASSWORD"] not in " ".join(args)
    assert "DB_ADMIN_PASSWORD" in args
    assert maintenance("check-model", path) == 0
    assert "DB_ADMIN_PASSWORD" not in calls[-1][0]


def test_missing_finbert_weights_has_actionable_error(monkeypatch):
    import sys
    from types import SimpleNamespace

    from src.platform.news import finbert

    def missing(*args, **kwargs):
        raise OSError("internal download location must not leak")

    loader = SimpleNamespace(from_pretrained=missing)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(
            AutoModelForSequenceClassification=loader, AutoTokenizer=loader, pipeline=None
        ),
    )
    finbert.cache_clear()
    with pytest.raises(ValueError, match="download-model") as error:
        finbert()
    assert "internal download location" not in str(error.value)
    finbert.cache_clear()


def test_compose_security_contract():
    # The parsed Compose model is supplied explicitly by the validation script/CI.
    import os

    config = os.environ.get("SI_TEST_COMPOSE_JSON")
    if not config:
        pytest.skip("Kein aufgelöstes Compose-Modell übergeben")
    model = json.loads(Path(config).read_text(encoding="utf-8-sig"))
    services = model["services"]
    assert set(services) == {"si-frontend", "si-backend", "si-postgres"}
    for name, service in services.items():
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert service["user"] not in {"root", "0", "0:0"}
        assert "container_name" not in service
        assert not any("docker.sock" in str(volume) for volume in service.get("volumes", []))
        if name != "si-frontend":
            assert not service.get("ports")
    assert services["si-frontend"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert model["networks"]["si-database"]["internal"] is True
