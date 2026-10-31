from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ...core import Settings
from ...memory import (
    MEMORY_KINDS,
    SCOPE_PREFIX,
    PowerContextClient,
    PowerContextError,
    memory_kind,
    project_from_scope_title,
    project_id_for_path,
    scope_title,
    validate_project_id,
)
from .library import bibliography_files


def require_enabled(settings: Settings) -> None:
    if not settings.memory_enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "记忆功能未启用",
                "hint": "设置 APP_MEMORY_ENABLED=true 并重启 citationproof serve",
            },
        )


def _powercontext_client(settings: Settings) -> PowerContextClient:
    token = settings.powercontext_token.get_secret_value() if settings.powercontext_token else None
    return PowerContextClient(
        settings.powercontext_base_url,
        token=token,
        timeout=settings.powercontext_timeout,
    )


def project_id(value: str | None, data_root: Path) -> str:
    if value:
        try:
            return validate_project_id(value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    for path in bibliography_files(data_root):
        try:
            return project_id_for_path(data_root, path)
        except ValueError:
            continue
    return "samples/bib"


def http_error(exc: PowerContextError) -> HTTPException:
    status = exc.status_code if exc.status_code and exc.status_code < 500 else 503
    return HTTPException(status_code=status, detail={"message": str(exc), "hint": exc.hint})


def list_projects(settings: Settings, data_root: Path) -> dict[str, Any]:
    require_enabled(settings)
    local: list[dict[str, Any]] = []
    for path in bibliography_files(data_root):
        try:
            project = project_id_for_path(data_root, path)
        except ValueError:
            continue
        local.append({"project": project, "title": scope_title(project), "scope_id": None})
    client = _powercontext_client(settings)
    try:
        scopes = client.list_scopes(SCOPE_PREFIX)
    except PowerContextError as exc:
        raise http_error(exc) from exc
    finally:
        client.close()

    by_project: dict[str, dict[str, Any]] = {}
    for scope in scopes:
        project = project_from_scope_title(str(scope.get("title", "")))
        if project is not None:
            by_project[project] = scope

    projects: list[dict[str, Any]] = []
    for item in local:
        scope = by_project.pop(item["project"], None)
        if scope is not None:
            item["scope_id"] = scope.get("scope_id")
            item["version"] = scope.get("version")
        projects.append(item)
    for project, scope in sorted(by_project.items()):
        projects.append(
            {
                "project": project,
                "title": scope.get("title"),
                "scope_id": scope.get("scope_id"),
                "version": scope.get("version"),
            }
        )
    default = local[0]["project"] if local else (projects[0]["project"] if projects else "")
    return {"projects": projects, "default": default, "kinds": list(MEMORY_KINDS)}


def list_entries(
    settings: Settings,
    data_root: Path,
    *,
    project: str | None,
    kind: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    require_enabled(settings)
    project_name = project_id(project, data_root)
    kind_filter: str | None = None
    if kind:
        try:
            kind_filter = memory_kind(kind)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc

    client = _powercontext_client(settings)
    try:
        scope = client.ensure_scope(scope_title(project_name), f"引据项目 {project_name}")
        scope_id = str(scope.get("scope_id", ""))
        entries = client.list_entries(scope_id, limit=None)
        handoff = client.continue_handoff(scope_id)
    except PowerContextError as exc:
        raise http_error(exc) from exc
    finally:
        client.close()

    counts = dict.fromkeys(MEMORY_KINDS, 0)
    for entry in entries:
        counts[entry.kind] = counts.get(entry.kind, 0) + 1
    filtered = [entry for entry in entries if kind_filter is None or entry.kind == kind_filter]
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    page = filtered[offset : offset + limit]
    return {
        "available": True,
        "project": project_name,
        "scope": scope,
        "entries": [entry.to_dict() for entry in page],
        "total": len(filtered),
        "counts": counts,
        "handoff": handoff.to_dict(),
        "kinds": list(MEMORY_KINDS),
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(page) < len(filtered),
    }


def search(
    settings: Settings,
    data_root: Path,
    *,
    query: str,
    project: str | None,
    limit: int,
) -> dict[str, Any]:
    require_enabled(settings)
    text = query.strip()
    if not text:
        raise HTTPException(status_code=400, detail={"message": "搜索内容不能为空"})
    if len(text) > 500:
        raise HTTPException(status_code=400, detail={"message": "搜索内容不能超过 500 个字符"})
    project_name = project_id(project, data_root)
    limit = max(1, min(int(limit), 50))

    client = _powercontext_client(settings)
    try:
        scope = client.ensure_scope(scope_title(project_name), f"引据项目 {project_name}")
        hits = client.search(str(scope.get("scope_id", "")), text, limit=limit)
    except PowerContextError as exc:
        raise http_error(exc) from exc
    finally:
        client.close()
    return {"available": True, "project": project_name, "query": text, "hits": hits}


def write_entry(
    settings: Settings,
    *,
    project: str,
    kind: str,
    text: str,
    reason: str | None,
) -> dict[str, Any]:
    require_enabled(settings)
    try:
        kind_name = memory_kind(kind)
        project_name = validate_project_id(project)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    content = text.strip()
    if not content:
        raise HTTPException(status_code=400, detail={"message": "记忆内容不能为空"})

    client = _powercontext_client(settings)
    try:
        scope = client.ensure_scope(scope_title(project_name), f"引据项目 {project_name}")
        scope_id = str(scope.get("scope_id", ""))
        existing = client.list_entries(scope_id, limit=None)
        if any(entry.kind == kind_name and entry.text == content for entry in existing):
            return {
                "available": True,
                "project": project_name,
                "changed": False,
                "records": [],
            }
        records = client.remember(
            scope_id,
            kind_name,
            content,
            reason=reason or "manual entry from workbench",
        )
    except PowerContextError as exc:
        raise http_error(exc) from exc
    finally:
        client.close()
    return {
        "available": True,
        "project": project_name,
        "changed": bool(records),
        "records": [record.to_dict() for record in records],
    }


def continue_handoff(
    settings: Settings,
    *,
    project: str,
) -> dict[str, Any]:
    require_enabled(settings)
    try:
        project_name = validate_project_id(project)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    client = _powercontext_client(settings)
    try:
        scope = client.ensure_scope(scope_title(project_name), f"引据项目 {project_name}")
        handoff = client.continue_handoff(str(scope.get("scope_id", "")))
    except PowerContextError as exc:
        raise http_error(exc) from exc
    finally:
        client.close()
    return {"available": True, "project": project_name, "handoff": handoff.to_dict()}
