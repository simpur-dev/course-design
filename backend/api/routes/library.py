from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ...evidence import EvidenceStore
from ...runtime import IngestSpec
from ..deps import ContextDep
from ..services import library as library_service
from ..services import uploads as upload_service

router = APIRouter(prefix="/api", tags=["library"])


@router.get("/papers")
def papers(context: ContextDep) -> dict[str, Any]:
    store = EvidenceStore(context.settings, None)
    try:
        records = store.list_papers()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": f"seekdb 不可用：{type(exc).__name__}: {exc}",
                "hint": "docker compose up -d seekdb；先执行 citationproof ingest --bib data/samples/bib.json",
            },
        ) from exc
    return {
        "papers": [asdict(record) for record in records],
        "count": len(records),
    }


@router.get("/drafts")
def drafts(context: ContextDep) -> dict[str, Any]:
    return {"drafts": library_service.draft_listing(context.data_root)}


@router.get("/bibliographies")
def bibliographies(context: ContextDep) -> dict[str, Any]:
    return {"bibliographies": library_service.bibliography_listing(context.data_root)}


@router.post("/uploads", status_code=202)
async def upload_pdf(
    request: Request,
    context: ContextDep,
    filename: str = Query(..., min_length=1, max_length=255),
    title: str = Query("", max_length=300),
    authors: str = Query("", max_length=300),
    year: int | None = Query(None, ge=1000, le=3000),
) -> JSONResponse:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in {"", "application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail={"message": "只接受 PDF 文件"})
    if upload_service.declared_too_large(request):
        raise upload_service.too_large()
    body = await upload_service.read_limited_body(request)
    if not body.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=400,
            detail={"message": "文件不是 PDF（缺少 %PDF- 文件头）"},
        )

    data_root: Path = context.data_root
    display = upload_service.safe_upload_name(filename)
    digest = hashlib.sha256(body).hexdigest()
    with context.upload_lock:
        if context.ingest_jobs.busy():
            raise HTTPException(
                status_code=409,
                detail={"message": context.ingest_jobs.busy_message},
            )
        entries = upload_service.load_upload_bib(data_root)
        duplicate = upload_service.find_duplicate(data_root, entries, digest)
        if duplicate is not None:
            key, ref = duplicate
            job = context.ingest_jobs.submit(
                IngestSpec(ref=ref),
                kind="ingest",
                stage="ingest",
                message="正在解析 PDF",
                paper_key=key,
            )
            return JSONResponse(
                status_code=202,
                content={
                    "job": context.ingest_jobs.snapshot(job),
                    "paper": upload_service.upload_paper(data_root, ref),
                    "duplicate": True,
                },
            )
        key = upload_service.upload_key(
            entries,
            upload_service.upload_slug(Path(display).stem),
            digest,
        )
        ref = upload_service.store_upload(
            data_root,
            entries,
            body=body,
            display=display,
            title=title,
            authors=authors,
            year=year,
            key=key,
        )
        job = context.ingest_jobs.submit(
            IngestSpec(ref=ref),
            kind="ingest",
            stage="ingest",
            message="正在解析 PDF",
            paper_key=key,
        )
        snapshot = context.ingest_jobs.snapshot(job)
    return JSONResponse(
        status_code=202,
        content={
            "job": snapshot,
            "paper": upload_service.upload_paper(data_root, ref),
            "duplicate": False,
        },
    )
