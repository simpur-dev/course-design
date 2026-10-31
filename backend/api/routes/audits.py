from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ...runtime import JobBusy, RunSpec
from ..deps import ContextDep
from ..schemas import AuditRequest
from ..services import library as library_service

router = APIRouter(prefix="/api", tags=["audits"])


@router.post("/audits", status_code=202)
def start_audit(payload: AuditRequest, context: ContextDep) -> JSONResponse:
    draft = library_service.resolve_data_path(context.data_root, payload.draft, {".md"})
    bib = library_service.resolve_data_path(context.data_root, payload.bib, {".json"})
    spec = RunSpec(
        draft=draft,
        bib=bib,
        paragraphs=payload.paragraphs,
        per_leg=payload.per_leg,
    )
    try:
        job = context.audit_jobs.submit(spec)
    except JobBusy as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc)}) from exc
    return JSONResponse(status_code=202, content={"job": context.audit_jobs.snapshot(job)})


@router.get("/jobs")
def jobs(context: ContextDep) -> dict[str, Any]:
    items = context.audit_jobs.recent() + context.ingest_jobs.recent()
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return {"jobs": items}


@router.get("/jobs/{job_id}")
def job_detail(job_id: str, context: ContextDep) -> dict[str, Any]:
    job = context.audit_jobs.get(job_id) or context.ingest_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"message": "任务不存在"})
    owner = context.audit_jobs if context.audit_jobs.get(job_id) is not None else context.ingest_jobs
    return {"job": owner.snapshot(job)}
