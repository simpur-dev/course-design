from __future__ import annotations

from ..audit.verdicts import BaselineVerifier, ChatVerifier
from ..core.config import Settings
from ..evidence.embeddings import EmbeddingCache, embedding_model_id
from ..evidence.store import EvidenceStore


class RuntimeConfigError(ValueError):
    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


def build_embedder(settings: Settings):
    if settings.embedding_provider != "local":
        raise RuntimeConfigError(
            f"embedding provider '{settings.embedding_provider}' is not implemented yet",
            "set APP_EMBEDDING_PROVIDER=local",
        )
    from pyseekdb import DefaultEmbeddingFunction

    return DefaultEmbeddingFunction()


def open_store(settings: Settings, embedder) -> EvidenceStore:
    try:
        return EvidenceStore(settings, embedder).ensure()
    except Exception as exc:
        raise RuntimeConfigError(
            f"seekdb unavailable: {type(exc).__name__}: {exc}",
            "docker compose up -d seekdb; then run 'citationproof doctor'",
        ) from exc


def open_cache(settings: Settings, embedder) -> EmbeddingCache:
    return EmbeddingCache(
        settings.data_dir / "runtime" / "embedding_cache.sqlite3",
        embedder,
        model_id=embedding_model_id(embedder),
    )


def build_verifier(settings: Settings):
    if settings.verifier_provider == "none":
        return BaselineVerifier()
    model = settings.verifier_model.strip()
    if not model:
        raise RuntimeConfigError(
            "verifier model is not configured",
            "set APP_VERIFIER_MODEL (and the provider API key) in .env",
        )
    if settings.verifier_provider == "openai":
        secret = settings.openai_api_key
        base_url = settings.openai_base_url
        key_hint = "APP_OPENAI_API_KEY"
    else:
        secret = settings.anthropic_api_key
        base_url = settings.anthropic_base_url
        key_hint = "APP_ANTHROPIC_API_KEY"
    if secret is None or not secret.get_secret_value():
        raise RuntimeConfigError(
            f"{settings.verifier_provider} verifier key missing",
            f"set {key_hint} in .env",
        )
    return ChatVerifier(
        provider=settings.verifier_provider,
        model=model,
        api_key=secret.get_secret_value(),
        base_url=base_url,
        timeout=settings.verifier_timeout,
    )
