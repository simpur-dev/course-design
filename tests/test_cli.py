import json

import pytest
import typer
from typer.testing import CliRunner

from backend import cli
from backend.audit.verdicts import BaselineVerifier, ChatVerifier
from backend.cli import deps as cli_deps
from backend.cli import main as cli_main
from backend.cli.commands import doctor as doctor_command
from backend.core.config import Settings
from backend.diagnostics.checks import Check

runner = CliRunner()


def _patch(monkeypatch, tmp_path, checks):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    monkeypatch.setattr(cli_main, "Settings", lambda: settings)
    monkeypatch.setattr(doctor_command, "run_checks", lambda settings: checks)


def test_version() -> None:
    result = runner.invoke(cli.app, ["version"])
    assert result.exit_code == 0
    assert "citationproof" in result.stdout


def test_doctor_ok(monkeypatch, tmp_path) -> None:
    _patch(
        monkeypatch,
        tmp_path,
        [Check("seekdb", True, "v1.4.0"), Check("powercontext", True, "ready")],
    )
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0
    assert "[OK" in result.stdout
    assert "seekdb" in result.stdout


def test_doctor_fails_with_nonzero_exit(monkeypatch, tmp_path) -> None:
    _patch(
        monkeypatch,
        tmp_path,
        [Check("seekdb", False, "down", "start it"), Check("powercontext", True, "ready")],
    )
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 1
    assert "FAIL" in result.stdout
    assert "hint: start it" in result.stdout


def test_doctor_json(monkeypatch, tmp_path) -> None:
    _patch(monkeypatch, tmp_path, [Check("seekdb", True, "ok")])
    result = runner.invoke(cli.app, ["doctor", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload == [{"name": "seekdb", "ok": True, "detail": "ok", "hint": None}]


def test_require_verifier_defaults_to_baseline() -> None:
    verifier = cli_deps.require_verifier(Settings(_env_file=None))
    assert isinstance(verifier, BaselineVerifier)
    assert verifier.name == "none/baseline"


def test_require_verifier_requires_model_and_key() -> None:
    with pytest.raises(typer.Exit):
        cli_deps.require_verifier(Settings(_env_file=None, verifier_provider="openai"))
    with pytest.raises(typer.Exit):
        cli_deps.require_verifier(
            Settings(_env_file=None, verifier_provider="openai", verifier_model="gpt-x")
        )


def test_require_verifier_returns_chat_adapter() -> None:
    settings = Settings(
        _env_file=None,
        verifier_provider="openai",
        verifier_model="gpt-x",
        openai_api_key="secret",
        openai_base_url="https://example.test/v1",
    )
    verifier = cli_deps.require_verifier(settings)
    assert isinstance(verifier, ChatVerifier)
    assert verifier.name == "openai:gpt-x"
