from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="YINJU_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    seekdb_host: str = "127.0.0.1"
    seekdb_port: int = 2881
    seekdb_user: str = "root"
    seekdb_password: SecretStr = SecretStr("")
    seekdb_database: str = "yinju"

    powercontext_host: str = "127.0.0.1"
    powercontext_port: int = 8000
    powercontext_token: SecretStr | None = None
    powercontext_timeout: float = 10.0
    memory_enabled: bool = True

    embedding_provider: Literal["local", "openai", "none"] = "local"
    verifier_provider: Literal["none", "openai", "anthropic"] = "none"
    verifier_model: str = ""
    verifier_timeout: float = 60.0
    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = None
    anthropic_api_key: SecretStr | None = None
    anthropic_base_url: str | None = None

    data_dir: Path = Path("data")
    web_dir: Path = Path("web/dist")
    web_host: str = "127.0.0.1"
    web_port: int = 8787
    log_level: str = "INFO"

    @property
    def powercontext_base_url(self) -> str:
        return f"http://{self.powercontext_host}:{self.powercontext_port}"
