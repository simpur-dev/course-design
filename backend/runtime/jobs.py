from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..audit import ProgressCallback
from ..evidence import PaperRef
from .providers import RuntimeConfigError


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
        self._update(job, status="running", progress=2, started_at=_now())
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


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
