import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_compose_services_and_healthchecks() -> None:
    data = _compose()
    services = data["services"]
    assert data["name"] == "course-design"
    assert set(services) == {"seekdb", "powercontext"}
    assert "@sha256:" in services["seekdb"]["image"]
    assert services["seekdb"]["healthcheck"]["test"]
    assert services["powercontext"]["healthcheck"]["test"]
    assert services["powercontext"]["build"]["context"] == "./deploy/powercontext"
    assert set(data["volumes"]) == {"seekdb-data", "powercontext-data"}


def test_compose_uses_configurable_host_ports() -> None:
    services = _compose()["services"]
    seekdb_ports = services["seekdb"]["ports"]
    pc_ports = services["powercontext"]["ports"]
    assert any("APP_SEEKDB_PORT" in port for port in seekdb_ports)
    assert any("APP_POWERCONTEXT_PORT" in port for port in pc_ports)


def test_powercontext_dockerfile_is_pinned() -> None:
    text = (ROOT / "deploy" / "powercontext" / "Dockerfile").read_text(encoding="utf-8")
    assert 'powercontext[cli,server]==1.4.0' in text
    assert "HEALTHCHECK" in text
    assert "USER powercontext" in text


def test_env_example_has_no_secrets() -> None:
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    assert values["APP_SEEKDB_PASSWORD"] == ""
    assert values["APP_OPENAI_API_KEY"] == ""
    assert values["APP_ANTHROPIC_API_KEY"] == ""
    assert not any("sk-" in value for value in values.values())


def test_project_script_entrypoint() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["scripts"]["citationproof"] == "backend.cli:app"
    assert data["project"]["requires-python"] == ">=3.11"
