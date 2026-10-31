from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from ..core import Settings
from ..runtime import JobManager


@dataclass
class AppContext:
    settings: Settings
    data_root: Path
    reports_root: Path
    frontend_root: Path | None
    audit_jobs: JobManager
    ingest_jobs: JobManager
    upload_lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def build(
        cls,
        settings: Settings,
        *,
        frontend_root: Path | None,
        audit_runner,
        ingest_runner,
    ) -> AppContext:
        data_root = Path(settings.data_dir).resolve()
        return cls(
            settings=settings,
            data_root=data_root,
            reports_root=data_root / "runtime" / "reports",
            frontend_root=frontend_root,
            audit_jobs=JobManager(audit_runner),
            ingest_jobs=JobManager(
                ingest_runner,
                busy_message="已有入库任务在运行，请等待完成",
            ),
        )
