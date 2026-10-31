from __future__ import annotations

from collections import Counter
from pathlib import Path

import typer

from ..audit import AuditReport, EvaluationReport
from ..evidence import IngestResult


def echo_evaluation_summary(
    report: EvaluationReport,
    files: dict[str, Path],
    err: bool = False,
) -> None:
    metrics = report.metrics
    typer.echo(
        f"eval: dataset={report.dataset} items={metrics['total']} | "
        f"labels supported={metrics['labels']['supported']} "
        f"unsupported={metrics['labels']['unsupported']} | "
        f"unsupported recall={fmt_ratio(metrics['unsupported_recall'])} "
        f"precision={fmt_ratio(metrics['unsupported_precision'])} | "
        f"handled={fmt_ratio(metrics['unsupported_handled_rate'])} "
        f"auto-pass={metrics['unsupported_auto_pass']} | "
        f"review={fmt_ratio(metrics['review_rate'])} | "
        f"evidence-page hit={fmt_ratio(metrics['evidence_page_hit_rate'])} | "
        f"errors={metrics['errors']}",
        err=err,
    )
    for kind in ("markdown", "json"):
        typer.echo(f"{kind}: {files[kind]}", err=err)


def fmt_ratio(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def echo_memory_summary(memory: dict[str, object], err: bool) -> None:
    if memory.get("ok"):
        handoff = memory.get("handoff") or {}
        revision = handoff.get("revision") if isinstance(handoff, dict) else None
        typer.echo(
            f"memory: project={memory.get('project')} scope={memory.get('scope_title')} "
            f"written={memory.get('written')} skipped={memory.get('skipped')} "
            f"handoff=r{revision if revision is not None else '-'}",
            err=err,
        )
        return
    typer.echo(f"memory: not written: {memory.get('error')}", err=True)


def echo_ingest_result(result: IngestResult) -> None:
    if result.status == "failed":
        typer.echo(f"[FAIL] {result.key:<16} {result.error}", err=True)
        return
    if result.status == "skipped":
        typer.echo(
            f"[SKIP] {result.key:<16} unchanged pages={result.page_count} "
            f"units={result.unit_count}; use --force to re-index"
        )
        return
    typer.echo(
        f"[{result.status.upper():<8}] {result.key:<16} pages={result.page_count} "
        f"para={result.para_count} sent={result.sent_count} "
        f"embedded={result.embedded} computed={result.computed} "
        f"cached={result.cached} {result.seconds:.2f}s"
    )


def echo_ingest_summary(results: list[IngestResult]) -> None:
    counts = Counter(result.status for result in results)
    typer.echo(
        f"total: {len(results)} papers | ingested={counts.get('ingested', 0)} "
        f"updated={counts.get('updated', 0)} skipped={counts.get('skipped', 0)} "
        f"failed={counts.get('failed', 0)}"
    )
    typer.echo(
        f"units: para={sum(result.para_count for result in results)} "
        f"sent={sum(result.sent_count for result in results)} | embeddings: "
        f"embedded={sum(result.embedded for result in results)} "
        f"computed={sum(result.computed for result in results)} "
        f"cached={sum(result.cached for result in results)}"
    )


def rank(value: int | None) -> str:
    return str(value) if value is not None else "-"


def echo_audit_summary(
    report: AuditReport,
    files: dict[str, Path],
    err: bool = False,
) -> None:
    counts = report.citation_verdicts
    typer.echo(
        f"claims={len(report.claims)} citations={report.citation_count} | "
        f"supported={counts.get('supported', 0)} partial={counts.get('partial', 0)} "
        f"unsupported={counts.get('unsupported', 0)} unknown={counts.get('unknown', 0)} | "
        f"review={report.review_count} errors={report.error_count}",
        err=err,
    )
    for kind in ("markdown", "csv", "json"):
        typer.echo(f"{kind}: {files[kind]}", err=err)
