from __future__ import annotations

import json
from pathlib import Path

import typer

from ...audit import (
    AuditEngine,
    AuditError,
    AuditReport,
    DraftError,
    parse_draft,
    report_to_dict,
    write_reports,
)
from ...core import Settings
from ...evidence import BibliographyError, embedding_model_id, load_bibliography
from ...memory import sync_report_memory
from ..deps import (
    fail,
    require_cache,
    require_embedder,
    require_store,
    require_verifier,
)
from ..output import echo_audit_summary, echo_memory_summary


def audit(
    ctx: typer.Context,
    draft: Path = typer.Option(  # noqa: B008 - Typer requires option calls in defaults
        Path("data/samples/draft.md"),
        "--draft",
        exists=True,
        dir_okay=False,
        help="Markdown draft with [@key] citations",
    ),
    bib: Path = typer.Option(  # noqa: B008 - Typer requires option calls in defaults
        Path("data/samples/bib.json"),
        "--bib",
        exists=True,
        dir_okay=False,
        help="bibliography JSON mapping paper keys to PDFs",
    ),
    out: Path = typer.Option(  # noqa: B008 - Typer requires option calls in defaults
        Path("data/runtime/reports"),
        "--out",
        help="directory for report.md / report.csv / report.json",
    ),
    paragraphs: int = typer.Option(5, "--paragraphs", min=1, max=10),
    per_leg: int = typer.Option(20, "--per-leg", min=1, max=100),
    memory: bool = typer.Option(
        True,
        "--memory/--no-memory",
        help="write criteria, verdicts and a Handoff to PowerContext",
    ),
    as_json: bool = typer.Option(False, "--json", help="print full report JSON to stdout"),
) -> None:
    """Audit every citation in a draft against its cited paper only."""
    settings: Settings = ctx.obj
    try:
        claims = parse_draft(draft)
        refs = load_bibliography(bib)
    except (DraftError, BibliographyError) as exc:
        fail(str(exc), "see data/samples/draft.md and data/samples/bib.json")

    cited = {citation for claim in claims for citation in claim.citations}
    unknown = sorted(cited - refs.keys())
    if unknown:
        fail(
            "draft cites keys missing from bibliography: " + ", ".join(unknown),
            f"add them to {bib}",
        )

    embedder = require_embedder(settings)
    store = require_store(settings, embedder)
    cache = require_cache(settings, embedder)
    verifier = require_verifier(settings)
    engine = AuditEngine(
        store,
        cache,
        verifier,
        embedding_model=embedding_model_id(embedder),
        paragraph_limit=paragraphs,
        per_leg=per_leg,
    )
    try:
        report = engine.audit(claims, refs, str(draft), str(bib))
    except AuditError as exc:
        fail(str(exc))
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports audit failures
        fail(f"audit failed: {type(exc).__name__}: {exc}")

    try:
        files = write_reports(report, out)
    except OSError as exc:
        fail(f"cannot write report: {exc}", f"check permissions for {out}")

    memory_payload = sync_memory(settings, report, bib, memory)

    if as_json:
        payload = report_to_dict(report)
        payload["files"] = {kind: str(path) for kind, path in files.items()}
        payload["memory"] = memory_payload
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        echo_audit_summary(report, files, err=True)
        echo_memory_summary(memory_payload, err=True)
    else:
        echo_audit_summary(report, files, err=False)
        echo_memory_summary(memory_payload, err=False)
    if report.error_count:
        raise typer.Exit(code=1)


def sync_memory(
    settings: Settings,
    report: AuditReport,
    bib: Path,
    enabled: bool,
) -> dict[str, object]:
    if enabled:
        return sync_report_memory(settings, report, bib).to_dict()
    return {
        "ok": False,
        "enabled": False,
        "project": None,
        "scope_title": None,
        "scope_id": None,
        "written": 0,
        "skipped": 0,
        "entries": [],
        "handoff": None,
        "error": "memory writes are disabled",
        "hint": "remove --no-memory to write project memory",
    }


def register(app: typer.Typer) -> None:
    app.command()(audit)
