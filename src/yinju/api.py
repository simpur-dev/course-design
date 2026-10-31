from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .audit import AuditEngine, ProgressCallback
from .bibliography import BibliographyError, PaperRef, load_bibliography
from .claims import parse_draft
from .config import Settings
from .doctor import run_checks
from .embeddings import embedding_model_id
from .ingest import ingest_paper
from .memory import (
    memory_kind,
    project_from_scope_title,
    project_id_for_path,
    scope_title,
    sync_report_memory,
    validate_project_id,
)
from .powercontext import MEMORY_KINDS, SCOPE_PREFIX, PowerContextClient, PowerContextError
from .report import report_to_dict, write_reports
from .runtime import (
    RuntimeConfigError,
    build_embedder,
    build_verifier,
    open_cache,
    open_store,
)
from .store import EvidenceStore

_RUN_ID = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_CITATION_MARK = re.compile(r"\[@[^\]]+\]")
_DRAFT_PREVIEW_CHARS = 20000
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_UPLOAD_ROOT = "uploads"
_UPLOAD_BIB = "bib.json"
_UPLOAD_PAPERS = "papers"
_upload_lock = threading.Lock()
_DOWNLOADS = {
    "markdown": ("report.md", "text/markdown; charset=utf-8"),
    "csv": ("report.csv", "text/csv; charset=utf-8"),
    "json": ("report.json", "application/json"),
}


class AuditRequest(BaseModel):
    draft: str = Field(..., min_length=1, max_length=512)
    bib: str = Field(..., min_length=1, max_length=512)
    paragraphs: int = Field(5, ge=1, le=10)
    per_leg: int = Field(20, ge=1, le=100)


class MemoryWriteRequest(BaseModel):
    project: str = Field(..., min_length=1, max_length=120)
    kind: str = Field(..., min_length=1, max_length=32)
    text: str = Field(..., min_length=1, max_length=2000)
    reason: str | None = Field(None, max_length=500)


class MemoryProjectRequest(BaseModel):
    project: str = Field(..., min_length=1, max_length=120)


@dataclass(frozen=True)
class RunSpec:
    draft: Path
    bib: Path
    paragraphs: int
    per_leg: int


@dataclass(frozen=True)
class IngestSpec:
    ref: PaperRef


@dataclass
class Job:
    id: str
    status: str = "queued"
    stage: str = "queued"
    progress: int = 0
    message: str = "排队中"
    created_at: str = field(default_factory=lambda: _now())
    started_at: str | None = None
    finished_at: str | None = None
    claim_id: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    hint: str | None = None
    kind: str = "audit"
    paper_key: str | None = None


class JobBusy(RuntimeError):
    pass


class JobManager:
    def __init__(
        self,
        runner: Callable[[Any, ProgressCallback], dict[str, Any]],
        busy_message: str = "已有核对任务在运行，请等待完成",
    ) -> None:
        self.runner = runner
        self.busy_message = busy_message
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        spec: RunSpec | IngestSpec,
        *,
        kind: str = "audit",
        stage: str = "preflight",
        message: str = "正在校验草稿与论文库",
        paper_key: str | None = None,
    ) -> Job:
        with self._lock:
            if any(job.status in {"queued", "running"} for job in self._jobs.values()):
                raise JobBusy(self.busy_message)
            job = Job(
                id=uuid.uuid4().hex[:12],
                kind=kind,
                stage=stage,
                message=message,
                paper_key=paper_key,
            )
            self._jobs[job.id] = job
        threading.Thread(target=self._run, args=(job, spec), daemon=True).start()
        return job

    def busy(self) -> bool:
        with self._lock:
            return any(job.status in {"queued", "running"} for job in self._jobs.values())

    def _run(self, job: Job, spec: RunSpec | IngestSpec) -> None:
        self._update(
            job,
            status="running",
            progress=2,
            started_at=_now(),
        )
        try:
            result = self.runner(spec, lambda event: self._progress(job, event))
        except Exception as exc:  # noqa: BLE001 - every job failure is reported to the UI
            hint = exc.hint if isinstance(exc, RuntimeConfigError) else None
            self._update(
                job,
                status="failed",
                stage="failed",
                progress=100,
                message=str(exc),
                error=f"{type(exc).__name__}: {exc}",
                hint=hint,
                finished_at=_now(),
            )
            return
        self._update(
            job,
            status="succeeded",
            stage="done",
            progress=100,
            message="入库完成" if job.kind == "ingest" else "核对完成",
            claim_id=None,
            result=result,
            finished_at=_now(),
        )

    def _progress(self, job: Job, event: dict[str, Any]) -> None:
        total = max(int(event.get("total") or 1), 1)
        done = min(max(int(event.get("done") or 0), 0), total)
        stage = str(event.get("stage") or "claim")
        if stage == "memory":
            progress = 98
        elif stage == "report":
            progress = 97
        else:
            progress = 3 + int(done * 93 / total)
        self._update(
            job,
            stage=stage,
            progress=min(progress, 98),
            message=str(event.get("message") or ""),
            claim_id=event.get("claim_id"),
        )

    def _update(self, job: Job, **changes: Any) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(job, key, value)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def snapshot(self, job: Job) -> dict[str, Any]:
        with self._lock:
            return asdict(job)

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)
            return [asdict(job) for job in jobs[:limit]]


def create_app(
    settings: Settings | None = None,
    runner: Callable[[RunSpec, ProgressCallback], dict[str, Any]] | None = None,
    ingest_runner: Callable[[IngestSpec, ProgressCallback], dict[str, Any]] | None = None,
) -> FastAPI:
    settings = settings or Settings()
    data_root = Path(settings.data_dir).resolve()
    reports_root = data_root / "runtime" / "reports"
    web_root = _resolve_web_root(settings)
    run_audit = runner or (lambda spec, progress: _run_audit(settings, spec, progress))
    run_ingest = ingest_runner or (
        lambda spec, progress: _run_ingest(settings, spec, progress)
    )
    manager = JobManager(run_audit)
    uploads = JobManager(run_ingest, busy_message="已有入库任务在运行，请等待完成")

    app = FastAPI(
        title="引据 CitationProof API",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.data_root = data_root
    app.state.reports_root = reports_root
    app.state.web_root = web_root
    app.state.jobs = manager
    app.state.upload_jobs = uploads

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        return {
            "version": __version__,
            "verifier": settings.verifier_provider,
            "verifier_model": settings.verifier_model or None,
            "embedding_provider": settings.embedding_provider,
            "baseline": settings.verifier_provider == "none",
            "memory_enabled": settings.memory_enabled,
            "web_built": web_root is not None,
            "baseline_notice": (
                "verifier=none：基线不出具 supported 结论；partial 表示高度相关但仍需人工确认。"
            ),
        }

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        checks = [asdict(check) for check in run_checks(settings)]
        return {"ok": all(check["ok"] for check in checks), "checks": checks}

    @app.get("/api/papers")
    def papers() -> dict[str, Any]:
        store = EvidenceStore(settings, None)
        try:
            records = store.list_papers()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "message": f"seekdb 不可用：{type(exc).__name__}: {exc}",
                    "hint": "docker compose up -d seekdb；先执行 yinju ingest --bib data/samples/bib.json",
                },
            ) from exc
        return {
            "papers": [asdict(record) for record in records],
            "count": len(records),
        }

    @app.get("/api/drafts")
    def drafts() -> dict[str, Any]:
        items = []
        for path in _data_files(data_root, ".md"):
            text = path.read_text(encoding="utf-8", errors="replace")
            items.append(
                {
                    "path": path.relative_to(data_root).as_posix(),
                    "name": path.stem,
                    "content": text[:_DRAFT_PREVIEW_CHARS],
                    "line_count": len(text.splitlines()),
                    "char_count": len(text),
                    "citation_count": len(_CITATION_MARK.findall(text)),
                    "truncated": len(text) > _DRAFT_PREVIEW_CHARS,
                    "updated_at": _timestamp(path),
                }
            )
        return {"drafts": items}

    @app.get("/api/bibliographies")
    def bibliographies() -> dict[str, Any]:
        items = [
            {
                "path": path.relative_to(data_root).as_posix(),
                "name": path.stem,
                "updated_at": _timestamp(path),
            }
            for path in _bibliography_files(data_root)
        ]
        return {"bibliographies": items}

    @app.post("/api/uploads", status_code=202)
    async def upload_pdf(
        request: Request,
        filename: str = Query(..., min_length=1, max_length=255),
        title: str = Query("", max_length=300),
        authors: str = Query("", max_length=300),
        year: int | None = Query(None, ge=1000, le=3000),
    ) -> JSONResponse:
        content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type not in {"", "application/pdf", "application/octet-stream"}:
            raise HTTPException(status_code=415, detail={"message": "只接受 PDF 文件"})
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
            raise _upload_too_large()
        body = await _read_limited_body(request)
        if not body.startswith(b"%PDF-"):
            raise HTTPException(
                status_code=400,
                detail={"message": "文件不是 PDF（缺少 %PDF- 文件头）"},
            )
        display = _safe_upload_name(filename)
        digest = hashlib.sha256(body).hexdigest()
        with _upload_lock:
            if uploads.busy():
                raise HTTPException(
                    status_code=409, detail={"message": uploads.busy_message}
                )
            entries = _load_upload_bib(data_root)
            duplicate = _find_upload_duplicate(data_root, entries, digest)
            if duplicate is not None:
                key, ref = duplicate
                job = uploads.submit(
                    IngestSpec(ref=ref),
                    kind="ingest",
                    stage="ingest",
                    message="正在解析 PDF",
                    paper_key=key,
                )
                return JSONResponse(
                    status_code=202,
                    content={
                        "job": uploads.snapshot(job),
                        "paper": _upload_paper(data_root, ref),
                        "duplicate": True,
                    },
                )
            key = _upload_key(entries, _upload_slug(Path(display).stem), digest)
            ref = _store_upload(
                data_root,
                entries,
                body=body,
                display=display,
                title=title,
                authors=authors,
                year=year,
                key=key,
            )
            job = uploads.submit(
                IngestSpec(ref=ref),
                kind="ingest",
                stage="ingest",
                message="正在解析 PDF",
                paper_key=key,
            )
            snapshot = uploads.snapshot(job)
        return JSONResponse(
            status_code=202,
            content={
                "job": snapshot,
                "paper": _upload_paper(data_root, ref),
                "duplicate": False,
            },
        )

    @app.get("/api/reports")
    def reports() -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for directory in _report_dirs(reports_root):
            payload = _read_report(directory)
            if payload is None:
                continue
            items.append(_report_summary(payload))
        return {"reports": items}

    @app.get("/api/reports/{run_id}")
    def report_detail(run_id: str) -> dict[str, Any]:
        directory = _find_report_dir(reports_root, run_id)
        payload = _read_report(directory)
        if payload is None:
            raise HTTPException(status_code=404, detail={"message": "报告不存在"})
        payload["downloads"] = _download_links(run_id)
        memory = _read_json(directory / "memory.json")
        if memory is not None:
            payload["memory"] = memory
        return payload

    @app.get("/api/reports/{run_id}/download/{kind}")
    def report_download(run_id: str, kind: str) -> FileResponse:
        if kind not in _DOWNLOADS:
            raise HTTPException(status_code=404, detail={"message": "不支持的报告格式"})
        directory = _find_report_dir(reports_root, run_id)
        filename, media_type = _DOWNLOADS[kind]
        path = directory / filename
        if not path.is_file():
            raise HTTPException(status_code=404, detail={"message": f"报告文件缺失：{filename}"})
        download_name = f"{run_id}-{filename}"
        return FileResponse(path, media_type=media_type, filename=download_name)

    @app.get("/api/memory/projects")
    def memory_projects() -> dict[str, Any]:
        _require_memory(settings)
        local: list[dict[str, Any]] = []
        for path in _bibliography_files(data_root):
            try:
                project = project_id_for_path(data_root, path)
            except ValueError:
                continue
            local.append(
                {"project": project, "title": scope_title(project), "scope_id": None}
            )
        client = _powercontext_client(settings)
        try:
            scopes = client.list_scopes(SCOPE_PREFIX)
        except PowerContextError as exc:
            raise _memory_http_error(exc) from exc
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

    @app.get("/api/memory")
    def memory_entries(
        project: str | None = None,
        kind: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        _require_memory(settings)
        project_id = _project_id(project, data_root)
        kind_filter: str | None = None
        if kind:
            try:
                kind_filter = memory_kind(kind)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc

        client = _powercontext_client(settings)
        try:
            scope = client.ensure_scope(scope_title(project_id), f"引据项目 {project_id}")
            scope_id = str(scope.get("scope_id", ""))
            entries = client.list_entries(scope_id, limit=None)
            handoff = client.continue_handoff(scope_id)
        except PowerContextError as exc:
            raise _memory_http_error(exc) from exc
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
            "project": project_id,
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

    @app.get("/api/memory/search")
    def memory_search(
        q: str,
        project: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        _require_memory(settings)
        query = q.strip()
        if not query:
            raise HTTPException(status_code=400, detail={"message": "搜索内容不能为空"})
        if len(query) > 500:
            raise HTTPException(status_code=400, detail={"message": "搜索内容不能超过 500 个字符"})
        project_id = _project_id(project, data_root)
        limit = max(1, min(int(limit), 50))

        client = _powercontext_client(settings)
        try:
            scope = client.ensure_scope(scope_title(project_id), f"引据项目 {project_id}")
            hits = client.search(str(scope.get("scope_id", "")), query, limit=limit)
        except PowerContextError as exc:
            raise _memory_http_error(exc) from exc
        finally:
            client.close()
        return {
            "available": True,
            "project": project_id,
            "query": query,
            "hits": hits,
        }

    @app.post("/api/memory/entries")
    def memory_write(payload: MemoryWriteRequest) -> dict[str, Any]:
        _require_memory(settings)
        try:
            kind = memory_kind(payload.kind)
            project_id = validate_project_id(payload.project)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
        text = payload.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail={"message": "记忆内容不能为空"})

        client = _powercontext_client(settings)
        try:
            scope = client.ensure_scope(scope_title(project_id), f"引据项目 {project_id}")
            scope_id = str(scope.get("scope_id", ""))
            existing = client.list_entries(scope_id, limit=None)
            if any(entry.kind == kind and entry.text == text for entry in existing):
                return {
                    "available": True,
                    "project": project_id,
                    "changed": False,
                    "records": [],
                }
            records = client.remember(
                scope_id,
                kind,
                text,
                reason=payload.reason or "manual entry from workbench",
            )
        except PowerContextError as exc:
            raise _memory_http_error(exc) from exc
        finally:
            client.close()
        return {
            "available": True,
            "project": project_id,
            "changed": bool(records),
            "records": [record.to_dict() for record in records],
        }

    @app.post("/api/memory/handoff/continue")
    def memory_handoff_continue(payload: MemoryProjectRequest) -> dict[str, Any]:
        _require_memory(settings)
        try:
            project_id = validate_project_id(payload.project)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
        client = _powercontext_client(settings)
        try:
            scope = client.ensure_scope(scope_title(project_id), f"引据项目 {project_id}")
            handoff = client.continue_handoff(str(scope.get("scope_id", "")))
        except PowerContextError as exc:
            raise _memory_http_error(exc) from exc
        finally:
            client.close()
        return {"available": True, "project": project_id, "handoff": handoff.to_dict()}

    @app.post("/api/audits", status_code=202)
    def start_audit(payload: AuditRequest) -> JSONResponse:
        draft = _resolve_data_path(data_root, payload.draft, {".md"})
        bib = _resolve_data_path(data_root, payload.bib, {".json"})
        spec = RunSpec(
            draft=draft,
            bib=bib,
            paragraphs=payload.paragraphs,
            per_leg=payload.per_leg,
        )
        try:
            job = manager.submit(spec)
        except JobBusy as exc:
            raise HTTPException(status_code=409, detail={"message": str(exc)}) from exc
        return JSONResponse(status_code=202, content={"job": manager.snapshot(job)})

    @app.get("/api/jobs")
    def jobs() -> dict[str, Any]:
        items = manager.recent() + uploads.recent()
        items.sort(key=lambda item: item["created_at"], reverse=True)
        return {"jobs": items}

    @app.get("/api/jobs/{job_id}")
    def job_detail(job_id: str) -> dict[str, Any]:
        job = manager.get(job_id) or uploads.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail={"message": "任务不存在"})
        owner = manager if manager.get(job_id) is not None else uploads
        return {"job": owner.snapshot(job)}

    _mount_frontend(app, web_root)
    return app


def _run_audit(settings: Settings, spec: RunSpec, progress: ProgressCallback) -> dict[str, Any]:
    claims = parse_draft(spec.draft)
    refs = load_bibliography(spec.bib)
    embedder = build_embedder(settings)
    store = open_store(settings, embedder)
    cache = open_cache(settings, embedder)
    verifier = build_verifier(settings)
    engine = AuditEngine(
        store,
        cache,
        verifier,
        embedding_model=embedding_model_id(embedder),
        paragraph_limit=spec.paragraphs,
        per_leg=spec.per_leg,
    )
    report = engine.audit(
        claims,
        refs,
        str(spec.draft),
        str(spec.bib),
        on_progress=progress,
    )
    files = write_reports(report, settings.data_dir / "runtime" / "reports")
    payload = report_to_dict(report)
    payload["files"] = {kind: str(path) for kind, path in files.items()}
    payload["downloads"] = _download_links(report.run_id)

    progress(
        {
            "stage": "memory",
            "done": len(report.claims),
            "total": len(report.claims),
            "message": "正在写入项目记忆与交接",
        }
    )
    try:
        memory = sync_report_memory(settings, report, spec.bib).to_dict()
    except Exception as exc:  # noqa: BLE001 - memory is additive; the report must survive
        memory = {
            "ok": False,
            "enabled": settings.memory_enabled,
            "project": None,
            "scope_title": None,
            "scope_id": None,
            "written": 0,
            "skipped": 0,
            "entries": [],
            "handoff": None,
            "error": f"{type(exc).__name__}: {exc}",
            "hint": "核对报告已生成；检查 PowerContext 后可在 #/memory 手动补写",
        }
    memory["written_at"] = _now()
    memory["run_id"] = report.run_id
    payload["memory"] = memory
    try:
        _write_json(files["json"].parent / "memory.json", memory)
    except OSError as exc:
        payload["memory"] = {
            **memory,
            "ok": False,
            "error": f"memory summary not written: {type(exc).__name__}: {exc}",
        }
    return payload


def _run_ingest(settings: Settings, spec: IngestSpec, progress: ProgressCallback) -> dict[str, Any]:
    progress({"stage": "ingest", "done": 0, "total": 1, "message": "正在解析 PDF"})
    embedder = build_embedder(settings)
    store = open_store(settings, embedder)
    cache = open_cache(settings, embedder)

    def on_progress(done: int, total: int) -> None:
        progress(
            {
                "stage": "ingest",
                "done": done,
                "total": total,
                "message": f"正在生成向量 {done}/{total} 批",
            }
        )

    return ingest_paper(spec.ref, store, cache, on_progress=on_progress).to_dict()


def _require_memory(settings: Settings) -> None:
    if not settings.memory_enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "记忆功能未启用",
                "hint": "设置 YINJU_MEMORY_ENABLED=true 并重启 yinju serve",
            },
        )


def _powercontext_client(settings: Settings) -> PowerContextClient:
    token = settings.powercontext_token.get_secret_value() if settings.powercontext_token else None
    return PowerContextClient(
        settings.powercontext_base_url,
        token=token,
        timeout=settings.powercontext_timeout,
    )


def _project_id(value: str | None, data_root: Path) -> str:
    if value:
        try:
            return validate_project_id(value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    for path in _bibliography_files(data_root):
        try:
            return project_id_for_path(data_root, path)
        except ValueError:
            continue
    return "samples/bib"


def _memory_http_error(exc: PowerContextError) -> HTTPException:
    status = exc.status_code if exc.status_code and exc.status_code < 500 else 503
    return HTTPException(status_code=status, detail={"message": str(exc), "hint": exc.hint})


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(tmp, path)


def _upload_root(data_root: Path) -> Path:
    return data_root / _UPLOAD_ROOT


def _upload_bib_path(data_root: Path) -> Path:
    return _upload_root(data_root) / _UPLOAD_BIB


def _upload_too_large() -> HTTPException:
    limit = MAX_UPLOAD_BYTES // (1024 * 1024)
    return HTTPException(
        status_code=413,
        detail={
            "message": f"PDF 不能超过 {limit} MB",
            "hint": "请压缩或拆分 PDF 后再上传",
        },
    )


async def _read_limited_body(request: Request) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise _upload_too_large()
        chunks.append(chunk)
    if size == 0:
        raise HTTPException(status_code=400, detail={"message": "上传内容为空"})
    return b"".join(chunks)


def _safe_upload_name(raw: str) -> str:
    name = PurePosixPath(raw.replace("\\", "/")).name
    if not name or name in {".", ".."} or "\x00" in name:
        raise HTTPException(
            status_code=400,
            detail={"message": "文件名不合法", "hint": "请使用常见的 PDF 文件名"},
        )
    return name[:200]


def _upload_slug(stem: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return slug[:40].strip("-") or "paper"


def _upload_key(entries: dict[str, Any], slug: str, digest: str) -> str:
    base = f"upload-{slug}"
    for length in (8, 12, 16, 32):
        candidate = f"{base}-{digest[:length]}"
        if candidate not in entries:
            return candidate
    return f"{base}-{uuid.uuid4().hex[:12]}"


def _load_upload_bib(data_root: Path) -> dict[str, Any]:
    path = _upload_bib_path(data_root)
    if not path.is_file():
        return {}
    payload = _read_json(path)
    if payload is None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"{path} 无法解析",
                "hint": "修复或移除该文件后再上传",
            },
        )
    return payload


def _find_upload_duplicate(
    data_root: Path,
    entries: dict[str, Any],
    digest: str,
) -> tuple[str, PaperRef] | None:
    root = _upload_root(data_root)
    for key, value in entries.items():
        if not isinstance(key, str):
            continue
        relative = value
        if isinstance(value, dict):
            relative = value.get("file")
        if not isinstance(relative, str) or not relative.strip():
            continue
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            continue
        if _file_sha256(path) != digest:
            continue
        metadata = value if isinstance(value, dict) else {}
        year = metadata.get("year")
        return key, PaperRef(
            key=key,
            file=path,
            title=str(metadata.get("title") or ""),
            authors=str(metadata.get("authors") or ""),
            year=year if isinstance(year, int) and not isinstance(year, bool) else None,
            source_url=str(metadata.get("source_url") or ""),
        )
    return None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _store_upload(
    data_root: Path,
    entries: dict[str, Any],
    *,
    body: bytes,
    display: str,
    title: str,
    authors: str,
    year: int | None,
    key: str,
) -> PaperRef:
    papers_dir = _upload_root(data_root) / _UPLOAD_PAPERS
    papers_dir.mkdir(parents=True, exist_ok=True)
    target = papers_dir / f"{key}.pdf"
    tmp = papers_dir / f".{key}.{uuid.uuid4().hex}.tmp"
    tmp.write_bytes(body)
    os.replace(tmp, target)

    clean_title = (title.strip() or Path(display).stem)[:300]
    clean_authors = authors.strip()[:300]
    entry: dict[str, Any] = {
        "file": target.relative_to(_upload_root(data_root)).as_posix(),
        "title": clean_title,
    }
    if clean_authors:
        entry["authors"] = clean_authors
    if year is not None:
        entry["year"] = year
    try:
        _write_json_atomic(_upload_bib_path(data_root), {**entries, key: entry})
    except OSError:
        target.unlink(missing_ok=True)
        raise
    return PaperRef(
        key=key,
        file=target,
        title=clean_title,
        authors=clean_authors,
        year=year,
    )


def _upload_paper(data_root: Path, ref: PaperRef) -> dict[str, Any]:
    return {
        "key": ref.key,
        "title": ref.title or ref.file.stem,
        "authors": ref.authors,
        "year": ref.year,
        "file": ref.file.relative_to(data_root).as_posix(),
    }


def _resolve_data_path(data_root: Path, raw: str, suffixes: set[str]) -> Path:
    if "\x00" in raw:
        raise HTTPException(status_code=400, detail={"message": "路径包含非法字符"})
    candidate = Path(raw)
    if not candidate.is_absolute():
        if candidate.parts and candidate.parts[0].lower() == data_root.name.lower():
            candidate = Path.cwd() / candidate
        else:
            candidate = data_root / candidate
    candidate = candidate.resolve()
    if not candidate.is_relative_to(data_root):
        raise HTTPException(
            status_code=400,
            detail={"message": "路径必须位于数据目录内"},
        )
    if candidate.suffix.lower() not in suffixes:
        allowed = ", ".join(sorted(suffixes))
        raise HTTPException(
            status_code=400,
            detail={"message": f"文件类型必须是以下之一：{allowed}"},
        )
    if not candidate.is_file():
        raise HTTPException(
            status_code=400,
            detail={"message": f"数据目录下找不到文件：{raw}"},
        )
    return candidate


def _data_files(data_root: Path, suffix: str) -> list[Path]:
    files: list[Path] = []
    if not data_root.is_dir():
        return files
    for path in data_root.rglob(f"*{suffix}"):
        relative = path.relative_to(data_root)
        if "runtime" in relative.parts or not path.is_file():
            continue
        if path.stat().st_size > 1_000_000:
            continue
        files.append(path)
    return sorted(files, key=lambda path: path.relative_to(data_root).as_posix())


def _bibliography_files(data_root: Path) -> list[Path]:
    usable: list[Path] = []
    for path in _data_files(data_root, ".json"):
        try:
            load_bibliography(path)
        except BibliographyError:
            continue
        usable.append(path)
    return usable


def _report_dirs(reports_root: Path) -> list[Path]:
    if not reports_root.is_dir():
        return []
    directories = [
        path
        for path in reports_root.iterdir()
        if path.is_dir() and (path / "report.json").is_file()
    ]
    return sorted(directories, key=lambda path: path.name, reverse=True)


def _find_report_dir(reports_root: Path, run_id: str) -> Path:
    if not _RUN_ID.match(run_id):
        raise HTTPException(status_code=404, detail={"message": "报告不存在"})
    for directory in _report_dirs(reports_root):
        payload = _read_report(directory)
        if payload is not None and payload.get("run_id") == run_id:
            return directory
    raise HTTPException(status_code=404, detail={"message": "报告不存在"})


def _read_report(directory: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _report_summary(payload: dict[str, Any]) -> dict[str, Any]:
    run_id = str(payload.get("run_id", ""))
    return {
        "run_id": run_id,
        "generated_at": payload.get("generated_at"),
        "draft": payload.get("draft"),
        "bib": payload.get("bib"),
        "verifier": payload.get("verifier"),
        "summary": payload.get("summary", {}),
        "warnings": payload.get("warnings", []),
        "downloads": _download_links(run_id),
    }


def _download_links(run_id: str) -> dict[str, str]:
    return {
        kind: f"/api/reports/{run_id}/download/{kind}" for kind in _DOWNLOADS
    }


def _resolve_web_root(settings: Settings) -> Path | None:
    candidate = Path(settings.web_dir)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    candidate = candidate.resolve()
    return candidate if (candidate / "index.html").is_file() else None


def _mount_frontend(app: FastAPI, web_root: Path | None) -> None:
    if web_root is not None:
        assets = web_root / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend(full_path: str) -> Any:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail={"message": "接口不存在"})
        if web_root is None:
            return JSONResponse(
                status_code=404,
                content={
                    "message": "前端尚未构建",
                    "hint": "先执行 npm --prefix web install && npm --prefix web run build",
                },
            )
        candidate = (web_root / full_path).resolve()
        if full_path and candidate.is_relative_to(web_root) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(web_root / "index.html")


def _timestamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(timespec="seconds")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def main() -> None:
    import uvicorn

    settings = Settings()
    uvicorn.run(
        create_app(settings),
        host=settings.web_host,
        port=settings.web_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
