from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..audit import (
    AuditEngine,
    ProgressCallback,
    parse_draft,
    report_to_dict,
    write_reports,
)
from ..core import Settings
from ..evidence import embedding_model_id, load_bibliography
from ..memory import sync_report_memory
from ..runtime import RunSpec
from ..runtime.providers import build_embedder, build_verifier, open_cache, open_store


class AuditAgent:
    """Single executing agent for the fixed audit pipeline.

    The v5 agent kernel (risk routing, bounded ReAct, checkpoints) grows here;
    it keeps one execution path and reuses the evidence, audit and memory layers.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(self, spec: RunSpec, progress: ProgressCallback) -> dict[str, Any]:
        settings = self.settings
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


def run_audit(settings: Settings, spec: RunSpec, progress: ProgressCallback) -> dict[str, Any]:
    return AuditAgent(settings).run(spec, progress)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
