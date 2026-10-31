from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..audit import AuditReport, ClaimCheck
from ..core.config import Settings
from .client import (
    MEMORY_KINDS,
    SCOPE_PREFIX,
    MemoryEntry,
    PowerContextClient,
    PowerContextError,
)

_PROJECT_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_MAX_PROJECT_LENGTH = 120
_MAX_DECISION_ENTRIES = 50
_MAX_NEXT_STEPS = 20
_HANDOFF_PENDING_STATEMENTS = 3

BASE_MEMORY: tuple[tuple[str, str], ...] = (
    ("criterion", "核对标准：只用被引论文原文作证据，判为支持时必须给出原句与页码。"),
    ("criterion", "核对标准：数字与实体必须与原文一致；检索失败或证据不足判为 unknown。"),
    ("criterion", "核对标准：无 key 基线不出具 supported，partial 一律标记人工复核。"),
    (
        "constraint",
        "范围约束：报告与界面使用简体中文；证据检索限定在论文库登记的论文内。",
    ),
)


@dataclass
class MemorySyncResult:
    ok: bool
    project: str
    scope_title: str
    scope_id: str | None = None
    written: int = 0
    skipped: int = 0
    entries: list[dict[str, Any]] = field(default_factory=list)
    handoff: dict[str, Any] | None = None
    error: str | None = None
    hint: str | None = None
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "enabled": self.enabled,
            "project": self.project,
            "scope_title": self.scope_title,
            "scope_id": self.scope_id,
            "written": self.written,
            "skipped": self.skipped,
            "entries": list(self.entries),
            "handoff": self.handoff,
            "error": self.error,
            "hint": self.hint,
        }


def validate_project_id(value: str) -> str:
    project = value.strip().strip("/")
    if not project or len(project) > _MAX_PROJECT_LENGTH:
        raise ValueError("项目名长度必须为 1–120 个字符")
    if any(part in {".", ".."} or not _PROJECT_SEGMENT.match(part) for part in project.split("/")):
        raise ValueError("项目名只能包含字母、数字、'.'、'_'、'-' 和 '/'")
    return project


def project_id_for_path(data_root: Path, path: Path) -> str:
    root = Path(data_root).resolve()
    candidate = Path(path).resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return validate_project_id(candidate.stem)
    return validate_project_id(relative.with_suffix("").as_posix())


def scope_title(project: str) -> str:
    return f"{SCOPE_PREFIX}{validate_project_id(project)}"


def project_from_scope_title(title: str) -> str | None:
    if not title.startswith(SCOPE_PREFIX):
        return None
    try:
        return validate_project_id(title[len(SCOPE_PREFIX) :])
    except ValueError:
        return None


def sync_report_memory(
    settings: Settings,
    report: AuditReport,
    bib_path: Path,
) -> MemorySyncResult:
    try:
        project = project_id_for_path(settings.data_dir, bib_path)
    except ValueError as exc:
        return MemorySyncResult(
            ok=False,
            enabled=settings.memory_enabled,
            project=Path(bib_path).stem,
            scope_title=f"{SCOPE_PREFIX}{Path(bib_path).stem}",
            error=f"项目名无效：{exc}",
            hint="检查 APP_DATA_DIR 下的文献库路径",
        )
    title = scope_title(project)
    if not settings.memory_enabled:
        return MemorySyncResult(
            ok=False,
            enabled=False,
            project=project,
            scope_title=title,
            error="记忆写入未启用",
            hint="设置 APP_MEMORY_ENABLED=true 后才会写入项目记忆",
        )
    token = settings.powercontext_token.get_secret_value() if settings.powercontext_token else None
    client = PowerContextClient(
        settings.powercontext_base_url,
        token=token,
        timeout=settings.powercontext_timeout,
    )
    try:
        return sync_with_client(client, project, report)
    except PowerContextError as exc:
        return MemorySyncResult(
            ok=False,
            project=project,
            scope_title=title,
            error=str(exc),
            hint=exc.hint,
        )
    finally:
        client.close()


def sync_with_client(
    client: PowerContextClient,
    project: str,
    report: AuditReport,
) -> MemorySyncResult:
    project = validate_project_id(project)
    title = scope_title(project)
    scope = client.ensure_scope(title, f"引据项目 {project}")
    scope_id = str(scope.get("scope_id", ""))
    if not scope_id:
        raise PowerContextError("PowerContext returned a scope without scope_id")

    existing = client.list_entries(scope_id, limit=None)
    known = {(entry.kind, entry.text): entry for entry in existing}
    written: list[MemoryEntry] = []
    skipped = 0

    def remember_once(kind: str, text: str, reason: str) -> MemoryEntry:
        nonlocal skipped
        entry = known.get((kind, text))
        if entry is not None:
            skipped += 1
            return entry
        records = client.remember(scope_id, kind, text, reason=reason)
        if not records:
            skipped += 1
            return MemoryEntry("", 0, kind, text, "unknown", 0)
        entry = records[0]
        known[(kind, text)] = entry
        written.append(entry)
        return entry

    base_entries: list[MemoryEntry] = []
    for kind, text in BASE_MEMORY:
        base_entries.append(remember_once(kind, text, f"run {report.run_id}"))

    decisions: list[MemoryEntry] = []
    for claim in report.claims[:_MAX_DECISION_ENTRIES]:
        decisions.append(
            remember_once("decision", claim_decision_text(report, claim), f"run {report.run_id}")
        )
    decision_by_claim = {
        claim.claim.claim_id: [entry.citation]
        for claim, entry in zip(report.claims[:_MAX_DECISION_ENTRIES], decisions, strict=True)
        if entry.artifact_id
    }
    summary_entry = remember_once(
        "decision", run_summary_text(report), f"run {report.run_id}"
    )

    next_steps: list[MemoryEntry] = []
    pending = [claim for claim in report.claims if is_pending(claim)]
    for claim in pending[:_MAX_NEXT_STEPS]:
        next_steps.append(
            remember_once("next_step", next_step_text(report, claim), f"run {report.run_id}")
        )
    next_by_claim = {
        claim.claim.claim_id: [entry.citation]
        for claim, entry in zip(pending[:_MAX_NEXT_STEPS], next_steps, strict=True)
        if entry.artifact_id
    }

    criterion_ref = _first_citation(base_entries, ("criterion",))
    summary_ref = _first_citation([summary_entry], ("decision",)) or criterion_ref
    decision_refs = _citations(decisions) or ([summary_ref] if summary_ref else [])
    next_refs = _citations(next_steps)

    draft = build_handoff_draft(
        report,
        project,
        summary_ref=summary_ref,
        criterion_ref=criterion_ref,
        decision_refs=decision_refs,
        next_refs=next_refs,
        decision_by_claim=decision_by_claim,
        next_by_claim=next_by_claim,
        pending=pending,
    )
    committed, resolved = client.commit_handoff(scope_id, draft)
    reference = committed.get("reference") or {}
    handoff = resolved.to_dict()
    handoff["revision"] = reference.get("revision", (resolved.current_revision or {}).get("revision"))
    handoff["committed"] = bool(reference)
    handoff["draft"] = draft

    return MemorySyncResult(
        ok=True,
        project=project,
        scope_title=title,
        scope_id=scope_id,
        written=len(written),
        skipped=skipped,
        entries=[entry.to_dict() for entry in written],
        handoff=handoff,
    )


def is_pending(claim: ClaimCheck) -> bool:
    return any(check.review_required for check in claim.checks) or claim.verdict == "unknown"


def claim_decision_text(report: AuditReport, claim: ClaimCheck) -> str:
    checks = ", ".join(f"@{check.citation}={check.verdict}" for check in claim.checks) or "无引用"
    reason = _claim_reason(claim)
    return (
        f"{report.run_id} · {claim.claim.claim_id} · {claim.verdict} · "
        f"主张：{claim.claim.text[:120]} · 引用：{checks} · 理由：{reason[:180]}"
    )


def run_summary_text(report: AuditReport) -> str:
    counts = report.citation_verdicts
    return (
        f"{report.run_id} · 核对完成 · {Path(report.draft_path).stem} · "
        f"主张 {len(report.claims)} 条、引用 {report.citation_count} 条 · "
        f"支持 {counts.get('supported', 0)} / 部分 {counts.get('partial', 0)} / "
        f"不支持 {counts.get('unsupported', 0)} / 无法判断 {counts.get('unknown', 0)} · "
        f"需复核 {report.review_count} 条、错误 {report.error_count} 条"
    )


def next_step_text(report: AuditReport, claim: ClaimCheck) -> str:
    return (
        f"{report.run_id} · 待复核 {claim.claim.claim_id}（{claim.verdict}）："
        f"{_claim_reason(claim)[:200]}"
    )


def build_handoff_draft(
    report: AuditReport,
    project: str,
    *,
    summary_ref: dict[str, Any] | None,
    criterion_ref: dict[str, Any] | None,
    decision_refs: list[dict[str, Any]],
    next_refs: list[dict[str, Any]],
    decision_by_claim: dict[str, list[dict[str, Any]]],
    next_by_claim: dict[str, list[dict[str, Any]]],
    pending: list[ClaimCheck],
) -> dict[str, Any]:
    fallback = summary_ref or criterion_ref or (decision_refs[0] if decision_refs else None)
    if fallback is None:
        raise PowerContextError("cannot build a Handoff without any memory citation")

    summary = (
        f"本次核对 {len(report.claims)} 条主张、{report.citation_count} 条引用："
        f"支持 {report.claim_verdicts.get('supported', 0)} / "
        f"部分支持 {report.claim_verdicts.get('partial', 0)} / "
        f"不支持 {report.claim_verdicts.get('unsupported', 0)} / "
        f"无法判断 {report.claim_verdicts.get('unknown', 0)}；"
        f"需人工复核 {report.review_count} 条。"
    )
    state = [
        {
            "text": summary,
            "citations": _unique([summary_ref, criterion_ref, fallback]),
        },
        {
            "text": (
                f"判定器 {report.verifier}；向量模型 {report.embedding_model}；"
                "证据检索限定在被引论文内。"
            ),
            "citations": [criterion_ref or fallback],
        },
    ]
    for claim in pending[:_HANDOFF_PENDING_STATEMENTS]:
        citations = _unique(
            decision_by_claim.get(claim.claim.claim_id, [])
            + next_by_claim.get(claim.claim.claim_id, [])
        )
        state.append(
            {
                "text": f"{claim.claim.claim_id}（{claim.verdict}）：{_claim_reason(claim)[:200]}",
                "citations": citations or [fallback],
            }
        )

    if pending:
        ids = "、".join(
            claim.claim.claim_id for claim in pending[:_HANDOFF_PENDING_STATEMENTS]
        )
        next_citations = _unique(
            [citation for claim in pending[:8] for citation in next_by_claim.get(claim.claim.claim_id, [])]
        )
        next_action = {
            "text": f"继续复核 {len(pending)} 条标记项：{ids}",
            "citations": next_citations or decision_refs[:1] or [fallback],
        }
        disposition = "continuable"
    else:
        next_action = {
            "text": "当前批次没有待复核项；可导入新草稿重新核对。",
            "citations": [criterion_ref or fallback],
        }
        disposition = "complete"

    omissions: list[dict[str, Any]] = []
    if len(pending) > _HANDOFF_PENDING_STATEMENTS:
        omissions.append(
            {
                "text": f"另有 {len(pending) - _HANDOFF_PENDING_STATEMENTS} 条待复核未逐条列入交接。",
                "citation": (next_refs or [fallback])[0],
            }
        )
    return {
        "objective": f"继续核对 {Path(report.draft_path).stem}（项目 {project}）",
        "state": state,
        "disposition": disposition,
        "next_action": next_action,
        "omissions": omissions,
    }


def _claim_reason(claim: ClaimCheck) -> str:
    for check in claim.checks:
        if check.verdict == claim.verdict:
            return check.reason
    if claim.checks:
        return claim.checks[0].reason
    return "无引用检查结果"


def _first_citation(
    entries: list[MemoryEntry],
    kinds: tuple[str, ...],
) -> dict[str, Any] | None:
    for entry in entries:
        if entry.kind in kinds and entry.artifact_id:
            return entry.citation
    return None


def _citations(entries: list[MemoryEntry]) -> list[dict[str, Any]]:
    return [entry.citation for entry in entries if entry.artifact_id]


def _unique(citations: list[dict[str, Any] | None]) -> list[dict[str, Any]]:
    seen: set[tuple[str, int]] = set()
    result: list[dict[str, Any]] = []
    for citation in citations:
        if citation is None:
            continue
        ref = citation.get("artifact_ref") or {}
        key = (str(ref.get("artifact_id", "")), int(ref.get("revision", 0)))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        result.append(citation)
    return result


def memory_kind(value: str) -> str:
    if value not in MEMORY_KINDS:
        raise ValueError(f"记忆类型必须是以下之一：{', '.join(MEMORY_KINDS)}")
    return value
