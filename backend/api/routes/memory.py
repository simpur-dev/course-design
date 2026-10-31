from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..deps import ContextDep
from ..schemas import MemoryProjectRequest, MemoryWriteRequest
from ..services import memory as memory_service

router = APIRouter(prefix="/api", tags=["memory"])


@router.get("/memory/projects")
def memory_projects(context: ContextDep) -> dict[str, Any]:
    return memory_service.list_projects(context.settings, context.data_root)


@router.get("/memory")
def memory_entries(
    context: ContextDep,
    project: str | None = None,
    kind: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    return memory_service.list_entries(
        context.settings,
        context.data_root,
        project=project,
        kind=kind,
        limit=limit,
        offset=offset,
    )


@router.get("/memory/search")
def memory_search(
    context: ContextDep,
    q: str,
    project: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    return memory_service.search(
        context.settings,
        context.data_root,
        query=q,
        project=project,
        limit=limit,
    )


@router.post("/memory/entries")
def memory_write(payload: MemoryWriteRequest, context: ContextDep) -> dict[str, Any]:
    return memory_service.write_entry(
        context.settings,
        project=payload.project,
        kind=payload.kind,
        text=payload.text,
        reason=payload.reason,
    )


@router.post("/memory/handoff/continue")
def memory_handoff_continue(
    payload: MemoryProjectRequest, context: ContextDep
) -> dict[str, Any]:
    return memory_service.continue_handoff(context.settings, project=payload.project)
