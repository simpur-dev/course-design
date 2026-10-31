from typing import Self

import httpx
from pydantic import SecretStr

from yinju import doctor
from yinju.config import Settings
from yinju.doctor import (
    check_data_dir,
    check_powercontext,
    check_providers,
    check_seekdb,
)


class FakeCursor:
    def __init__(self, database_exists: bool) -> None:
        self.database_exists = database_exists
        self.sql = ""

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args) -> bool:
        return False

    def execute(self, sql: str, params=None) -> None:
        self.sql = sql

    def fetchone(self):
        if "version()" in self.sql:
            return ("5.7.25-OceanBase seekdb-v1.4.0.0",)
        return ("yinju",) if self.database_exists else None


class FakeConnection:
    def __init__(self, database_exists: bool) -> None:
        self.database_exists = database_exists
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.database_exists)

    def close(self) -> None:
        self.closed = True


def _settings(tmp_path, **overrides) -> Settings:
    overrides.setdefault("data_dir", tmp_path)
    return Settings(_env_file=None, **overrides)


def test_seekdb_ok(monkeypatch, tmp_path) -> None:
    connection = FakeConnection(database_exists=True)
    monkeypatch.setattr(doctor.pymysql, "connect", lambda **kwargs: connection)
    result = check_seekdb(_settings(tmp_path))
    assert result.ok
    assert "seekdb-v1.4.0.0" in result.detail
    assert "exists" in result.detail
    assert connection.closed


def test_seekdb_reports_missing_database(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        doctor.pymysql, "connect", lambda **kwargs: FakeConnection(database_exists=False)
    )
    result = check_seekdb(_settings(tmp_path))
    assert result.ok
    assert "missing" in result.detail


def test_seekdb_failure(monkeypatch, tmp_path) -> None:
    def boom(**kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(doctor.pymysql, "connect", boom)
    result = check_seekdb(_settings(tmp_path))
    assert not result.ok
    assert "connection refused" in result.detail
    assert result.hint


def _mock_client(ready_status: int = 200, version: str = "1.4.0") -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health/ready":
            return httpx.Response(ready_status, json={"status": "ready"})
        if request.url.path == "/openapi.json":
            return httpx.Response(200, json={"info": {"version": version}})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_powercontext_ok(tmp_path) -> None:
    result = check_powercontext(_settings(tmp_path), client=_mock_client())
    assert result.ok
    assert "v1.4.0" in result.detail


def test_powercontext_failure(tmp_path) -> None:
    result = check_powercontext(_settings(tmp_path), client=_mock_client(ready_status=503))
    assert not result.ok
    assert "503" in result.detail


def test_powercontext_unreachable(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = check_powercontext(_settings(tmp_path), client=client)
    assert not result.ok
    assert "ConnectError" in result.detail


def test_providers_default_ok(tmp_path) -> None:
    result = check_providers(_settings(tmp_path))
    assert result.ok
    assert "embedding=local" in result.detail


def test_providers_require_key(tmp_path) -> None:
    settings = _settings(tmp_path, embedding_provider="openai", verifier_provider="openai")
    result = check_providers(settings)
    assert not result.ok
    assert "YINJU_OPENAI_API_KEY" in result.detail


def test_providers_accept_configured_key(tmp_path) -> None:
    settings = _settings(
        tmp_path,
        verifier_provider="anthropic",
        anthropic_api_key=SecretStr("placeholder"),
    )
    assert check_providers(settings).ok


def test_data_dir_ok(tmp_path) -> None:
    result = check_data_dir(_settings(tmp_path / "data"))
    assert result.ok
    assert (tmp_path / "data").is_dir()


def test_data_dir_failure(tmp_path) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    result = check_data_dir(_settings(tmp_path, data_dir=blocked))
    assert not result.ok
    assert result.hint
