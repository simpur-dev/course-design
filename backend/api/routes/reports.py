from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse

from ..deps import ContextDep
from ..services import reports as report_service

router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/reports")
def reports(context: ContextDep) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for directory in report_service.report_dirs(context.reports_root):
        payload = report_service.read_report(directory)
        if payload is None:
            continue
        items.append(report_service.report_summary(payload))
    return {"reports": items}


@router.get("/reports/{run_id}")
def report_detail(run_id: str, context: ContextDep) -> dict[str, Any]:
    return report_service.report_detail(context.reports_root, run_id)


@router.get("/reports/{run_id}/download/{kind}")
def report_download(run_id: str, kind: str, context: ContextDep) -> FileResponse:
    path, media_type, download_name = report_service.report_file(
        context.reports_root, run_id, kind
    )
    return FileResponse(path, media_type=media_type, filename=download_name)
