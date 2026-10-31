from __future__ import annotations

import logging
from typing import NoReturn

import typer

from ..core import Settings
from ..evidence import EmbeddingCache, EvidenceStore
from ..runtime import (
    RuntimeConfigError,
    build_embedder,
    build_verifier,
    open_cache,
    open_store,
)


def configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), None)
    if not isinstance(level, int):
        level = logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if level > logging.DEBUG:
        for name in ("httpx", "pyseekdb"):
            logging.getLogger(name).setLevel(logging.WARNING)


def fail(message: str, hint: str | None = None) -> NoReturn:
    typer.echo(message, err=True)
    if hint:
        typer.echo(f"hint: {hint}", err=True)
    raise typer.Exit(code=1)


def require_embedder(settings: Settings):
    try:
        return build_embedder(settings)
    except RuntimeConfigError as exc:
        fail(str(exc), exc.hint)


def require_store(settings: Settings, embedder) -> EvidenceStore:
    try:
        return open_store(settings, embedder)
    except RuntimeConfigError as exc:
        fail(str(exc), exc.hint)


def require_cache(settings: Settings, embedder) -> EmbeddingCache:
    return open_cache(settings, embedder)


def require_verifier(settings: Settings):
    try:
        return build_verifier(settings)
    except RuntimeConfigError as exc:
        fail(str(exc), exc.hint)
