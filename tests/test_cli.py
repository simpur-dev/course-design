import json

import pytest
import typer
from typer.testing import CliRunner

from yinju import cli
from yinju.config import Settings
from yinju.doctor import Check
from yinju.verdicts import BaselineVerifier, ChatVerifier

runner = CliRunner()


def _patch(monkeypatch, tmp_path, checks):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli, "run_checks", lambda settings: checks)


def test_version() -> None:
    result = runner.invoke(cli.app, ["version"])
    assert result.exit_code == 0
    assert "yinju" in result.stdout


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


def test_build_verifier_defaults_to_baseline() -> None:
    verifier = cli._build_verifier(Settings(_env_file=None))
    assert isinstance(verifier, BaselineVerifier)
    assert verifier.name == "none/baseline"


def test_build_verifier_requires_model_and_key() -> None:
    with pytest.raises(typer.Exit):
        cli._build_verifier(Settings(_env_file=None, verifier_provider="openai"))
    with pytest.raises(typer.Exit):
        cli._build_verifier(
            Settings(_env_file=None, verifier_provider="openai", verifier_model="gpt-x")
        )


def test_build_verifier_returns_chat_adapter() -> None:
    settings = Settings(
        _env_file=None,
        verifier_provider="openai",
        verifier_model="gpt-x",
        openai_api_key="secret",
        openai_base_url="https://example.test/v1",
    )
    verifier = cli._build_verifier(settings)
    assert isinstance(verifier, ChatVerifier)
    assert verifier.name == "openai:gpt-x"
