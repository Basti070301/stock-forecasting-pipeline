"""Preview isolation/configuration tests. Actual container evidence is separate."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from scripts.configure_docker import generate
from scripts.docker_admin import load_environment, maintenance
from src.platform.api import create_app
from src.platform.config import Settings
from src.platform.current_forecasts import CurrentForecastPipeline
from src.platform.docker_preview import require_preview, seed_reference_files
from src.platform.forecast_contract import ForecastError
from src.platform.store import Store


def test_preview_configuration_is_separate_versioned_and_loopback(tmp_path):
    env = tmp_path / ".env.preview"
    assert (
        generate(
            env,
            port=8086,
            project="stockintelligence-m43-test-unit",
            preview=True,
            image_tag="m43-unit",
        )
        == "https://127.0.0.1:8086"
    )
    values = load_environment(env)
    assert values["SI_DEPLOYMENT_PROFILE"] == "historical-preview"
    assert values["SI_BACKEND_IMAGE"].endswith(":m43-unit")
    assert values["SI_FINBERT_ENABLED"] == "false"
    assert values["SI_DB_APP_PASSWORD"] != values["SI_DB_ADMIN_PASSWORD"]
    before = env.read_bytes()
    with pytest.raises(FileExistsError):
        generate(
            env,
            port=8086,
            project="stockintelligence-m43-test-unit",
            preview=True,
            image_tag="m43-unit",
        )
    assert env.read_bytes() == before


@pytest.mark.parametrize(
    "changes",
    [
        {"bind": "192.168.1.10"},
        {"project": "foreign-stack"},
        {"image_tag": "latest"},
        {"image_tag": "m22"},
    ],
)
def test_preview_refuses_ambiguous_or_shared_configuration(tmp_path, changes):
    options = {
        "project": "stockintelligence-m43-test-unit",
        "preview": True,
        "image_tag": "m43-unit",
    } | changes
    with pytest.raises(ValueError):
        generate(tmp_path / ".env.preview", **options)


def test_admin_uses_overlay_without_disabling_http_read_profile(tmp_path, monkeypatch):
    env = tmp_path / ".env.preview"
    generate(
        env,
        port=8086,
        project="stockintelligence-m43-test-unit",
        preview=True,
        image_tag="m43-unit",
    )
    run = Mock(return_value=type("Result", (), {"returncode": 0})())
    monkeypatch.setattr("scripts.docker_admin.subprocess.run", run)
    assert maintenance("replay-research", env) == 0
    arguments = run.call_args.args[0]
    assert "compose.preview.yaml" in arguments
    assert "SI_ALLOW_MUTATIONS=true" not in arguments
    assert "DB_ADMIN_PASSWORD" in arguments
    assert load_environment(env)["SI_DB_ADMIN_PASSWORD"] not in " ".join(arguments)
    assert maintenance("prepare-research", env) == 0
    assert "DB_ADMIN_PASSWORD" not in run.call_args.args[0]


def test_preview_commands_reject_regular_deployment(tmp_path, monkeypatch):
    env = tmp_path / ".env.docker"
    generate(env)
    run = Mock()
    monkeypatch.setattr("scripts.docker_admin.subprocess.run", run)
    with pytest.raises(ValueError):
        maintenance("prepare-research", env)
    run.assert_not_called()


def test_historical_read_profile_never_activates_current_or_ui_mutations(tmp_path):
    settings = Settings(
        _env_file=None,
        runtime_dir=tmp_path,
        historical_preview=True,
        allow_mutations=False,
        current_auto_refresh=True,
        current_enabled=True,
    )
    store = Store(settings)
    store.migrate()
    with pytest.raises(ForecastError) as error:
        CurrentForecastPipeline(store).gate()
    assert error.value.code == "historical_preview"
    with TestClient(create_app(settings, store)) as client:
        result = client.get("/api/settings").json()
        assert result["data_profile"] == "historical_preview" and not result["allow_mutations"]
        assert client.post("/api/forecasts/current", json={"tickers": ["AAPL"]}).status_code == 403
        assert client.post("/api/forecasts/research", json={}).status_code == 403
        assert not client.get("/api/research/current/status").json()["scheduler"]["running"]
    store.engine.dispose()


def test_preview_root_and_provider_controls_are_enforced(tmp_path):
    settings = Settings(
        _env_file=None, runtime_dir=tmp_path, historical_preview=True, allow_mutations=False
    )
    assert require_preview(settings) == tmp_path / "preview-models"
    for changes in (
        {"allow_mutations": True},
        {"current_enabled": True},
        {"market_enabled": True},
        {"news_auto_refresh": True},
        {"research_artifact_dir": tmp_path.parent / "outside"},
    ):
        with pytest.raises(ValueError):
            require_preview(settings.model_copy(update=changes))


def test_reference_file_seed_is_idempotent_and_never_overwrites(tmp_path, monkeypatch):
    from src.platform import docker_preview

    monkeypatch.setattr(docker_preview, "PROJECT_ROOT", tmp_path)
    source = tmp_path / "reference/raw"
    for folder, suffix in (("prices", "csv"), ("profiles", "json")):
        (source / folder).mkdir(parents=True)
        for ticker in ("AAPL", "MSFT", "NVDA", "SAP_DE", "ALV_DE"):
            (source / folder / f"{ticker}_20260825T213028Z.{suffix}").write_text(
                "explicit storage fixture"
            )
    assert seed_reference_files() == 10
    assert seed_reference_files() == 0
    target = tmp_path / "data/raw/prices/AAPL_20260825T213028Z.csv"
    target.write_text("existing data to preserve")
    with pytest.raises(ValueError):
        seed_reference_files()
    assert target.read_text() == "existing data to preserve"


def test_image_includes_frozen_protocol_and_preview_dependencies():
    source = Path("Dockerfile").read_text()
    assert "m4_2_prospective_protocol_v1.json" in source
    assert "COPY data/raw/ data/raw/" in source
    assert "--require-hashes" in source
    assert "snapshot_download" not in source
    assert ".runtime" in Path(".dockerignore").read_text().splitlines()
    assert "--frozen-lockfile" in Path("deploy/frontend/Dockerfile").read_text()
    protocol = Path("reports/research/m4_2_prospective_protocol_v1.json")
    assert json.loads(protocol.read_text())["independent_validation"] == "not_started"
