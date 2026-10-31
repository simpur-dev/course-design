from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter

from ... import __version__
from ...diagnostics import run_checks
from ..deps import ContextDep

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/config")
def config(context: ContextDep) -> dict[str, Any]:
    settings = context.settings
    return {
        "version": __version__,
        "verifier": settings.verifier_provider,
        "verifier_model": settings.verifier_model or None,
        "embedding_provider": settings.embedding_provider,
        "baseline": settings.verifier_provider == "none",
        "memory_enabled": settings.memory_enabled,
        "frontend_built": context.frontend_root is not None,
        "baseline_notice": (
            "verifier=none：基线不出具 supported 结论；partial 表示高度相关但仍需人工确认。"
        ),
    }


@router.get("/health")
def health(context: ContextDep) -> dict[str, Any]:
    checks = [asdict(check) for check in run_checks(context.settings)]
    return {"ok": all(check["ok"] for check in checks), "checks": checks}
