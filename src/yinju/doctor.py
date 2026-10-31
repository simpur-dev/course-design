from __future__ import annotations

from dataclasses import asdict, dataclass

import httpx
import pymysql
from pydantic import SecretStr

from .config import Settings


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    hint: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _has_secret(value: SecretStr | None) -> bool:
    return bool(value and value.get_secret_value().strip())


def check_data_dir(settings: Settings) -> Check:
    path = settings.data_dir
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return Check("data", True, f"{path.resolve()} (writable)")
    except OSError as exc:
        return Check(
            "data",
            False,
            f"{path}: {type(exc).__name__}: {exc}",
            "check YINJU_DATA_DIR and its permissions",
        )


def check_seekdb(settings: Settings) -> Check:
    try:
        connection = pymysql.connect(
            host=settings.seekdb_host,
            port=settings.seekdb_port,
            user=settings.seekdb_user,
            password=settings.seekdb_password.get_secret_value(),
            connect_timeout=3,
            read_timeout=5,
            write_timeout=5,
            charset="utf8mb4",
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT version()")
                row = cursor.fetchone()
                version = row[0] if row else "unknown"
                cursor.execute(
                    "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s",
                    (settings.seekdb_database,),
                )
                database_exists = cursor.fetchone() is not None
        finally:
            connection.close()
    except Exception as exc:  # noqa: BLE001 - doctor reports any driver failure
        return Check(
            "seekdb",
            False,
            f"{settings.seekdb_host}:{settings.seekdb_port} -> {type(exc).__name__}: {exc}",
            "docker compose up -d seekdb; check YINJU_SEEKDB_PORT",
        )

    state = "exists" if database_exists else "missing (created on first ingest)"
    return Check("seekdb", True, f"{version}; database={settings.seekdb_database} {state}")


def check_powercontext(settings: Settings, client: httpx.Client | None = None) -> Check:
    owns_client = client is None
    client = client or httpx.Client(timeout=5.0)
    headers: dict[str, str] = {}
    if _has_secret(settings.powercontext_token):
        assert settings.powercontext_token is not None
        headers["Authorization"] = f"Bearer {settings.powercontext_token.get_secret_value()}"

    base = settings.powercontext_base_url
    try:
        ready = client.get(f"{base}/health/ready", headers=headers)
        if ready.status_code != 200:
            return Check(
                "powercontext",
                False,
                f"{base}/health/ready -> HTTP {ready.status_code}",
                "docker compose up -d powercontext; check YINJU_POWERCONTEXT_PORT",
            )
        version = "unknown"
        try:
            spec = client.get(f"{base}/openapi.json", headers=headers)
            if spec.status_code == 200:
                version = spec.json().get("info", {}).get("version", "unknown")
        except (httpx.HTTPError, ValueError):
            pass
        return Check("powercontext", True, f"v{version} ready at {base}")
    except httpx.HTTPError as exc:
        return Check(
            "powercontext",
            False,
            f"{base} -> {type(exc).__name__}: {exc}",
            "docker compose up -d powercontext; check YINJU_POWERCONTEXT_PORT",
        )
    finally:
        if owns_client:
            client.close()


def check_providers(settings: Settings) -> Check:
    problems: list[str] = []
    if settings.embedding_provider == "openai" and not _has_secret(settings.openai_api_key):
        problems.append("embedding=openai but YINJU_OPENAI_API_KEY is empty")
    if settings.verifier_provider == "openai" and not _has_secret(settings.openai_api_key):
        problems.append("verifier=openai but YINJU_OPENAI_API_KEY is empty")
    if settings.verifier_provider == "anthropic" and not _has_secret(settings.anthropic_api_key):
        problems.append("verifier=anthropic but YINJU_ANTHROPIC_API_KEY is empty")

    detail = f"embedding={settings.embedding_provider} verifier={settings.verifier_provider}"
    if settings.embedding_provider == "local":
        detail += " (model downloads on first ingest)"
    if problems:
        return Check("providers", False, f"{detail}; " + "; ".join(problems), "fill .env or pick none/local")
    return Check("providers", True, detail)


def run_checks(settings: Settings, client: httpx.Client | None = None) -> list[Check]:
    return [
        check_data_dir(settings),
        check_seekdb(settings),
        check_powercontext(settings, client),
        check_providers(settings),
    ]
