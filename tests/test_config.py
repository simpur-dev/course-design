import os

from backend.core.config import Settings


def _clear_app_env(monkeypatch) -> None:
    for key in list(os.environ):
        if key.startswith("APP_"):
            monkeypatch.delenv(key, raising=False)


def test_defaults(monkeypatch) -> None:
    _clear_app_env(monkeypatch)
    settings = Settings(_env_file=None)
    assert settings.seekdb_host == "127.0.0.1"
    assert settings.seekdb_port == 2881
    assert settings.seekdb_database == "course_design"
    assert settings.powercontext_base_url == "http://127.0.0.1:8000"
    assert settings.embedding_provider == "local"
    assert settings.verifier_provider == "none"
    assert settings.seekdb_password.get_secret_value() == ""
    assert settings.frontend_dir.name == "dist"
    assert settings.server_port == 8787


def test_env_override(monkeypatch) -> None:
    _clear_app_env(monkeypatch)
    monkeypatch.setenv("APP_SEEKDB_PORT", "2884")
    monkeypatch.setenv("APP_POWERCONTEXT_HOST", "pc.local")
    monkeypatch.setenv("APP_POWERCONTEXT_PORT", "18000")
    monkeypatch.setenv("APP_EMBEDDING_PROVIDER", "none")
    settings = Settings(_env_file=None)
    assert settings.seekdb_port == 2884
    assert settings.powercontext_base_url == "http://pc.local:18000"
    assert settings.embedding_provider == "none"


def test_secret_is_masked(monkeypatch) -> None:
    _clear_app_env(monkeypatch)
    monkeypatch.setenv("APP_SEEKDB_PASSWORD", "super-secret-value")
    settings = Settings(_env_file=None)
    assert settings.seekdb_password.get_secret_value() == "super-secret-value"
    assert "super-secret-value" not in repr(settings)
