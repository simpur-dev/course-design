from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import NoReturn

import typer

from . import __version__
from .audit import AuditEngine, AuditError, AuditReport
from .bibliography import BibliographyError, load_bibliography
from .claims import DraftError, parse_draft
from .config import Settings
from .doctor import run_checks
from .embeddings import EmbeddingCache, embedding_model_id
from .evaluation import (
    EvaluationReport,
    LabelError,
    evaluate,
    evaluation_to_dict,
    load_labeled_set,
    write_evaluation,
)
from .ingest import IngestResult, ingest_bibliography
from .memory import sync_report_memory
from .report import report_to_dict, write_reports
from .runtime import (
    RuntimeConfigError,
    build_embedder,
    build_verifier,
    open_cache,
    open_store,
)
from .store import RRF_RANK_CONSTANT, EvidenceStore
from .terms import extract_keywords

app = typer.Typer(help="引据 CitationProof CLI", no_args_is_help=True)


def _configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), None)
    if not isinstance(level, int):
        level = logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if level > logging.DEBUG:
        for name in ("httpx", "pyseekdb"):
            logging.getLogger(name).setLevel(logging.WARNING)


def _fail(message: str, hint: str | None = None) -> NoReturn:
    typer.echo(message, err=True)
    if hint:
        typer.echo(f"hint: {hint}", err=True)
    raise typer.Exit(code=1)


def _build_embedder(settings: Settings):
    try:
        return build_embedder(settings)
    except RuntimeConfigError as exc:
        _fail(str(exc), exc.hint)


def _open_store(settings: Settings, embedder) -> EvidenceStore:
    try:
        return open_store(settings, embedder)
    except RuntimeConfigError as exc:
        _fail(str(exc), exc.hint)


def _open_cache(settings: Settings, embedder) -> EmbeddingCache:
    return open_cache(settings, embedder)


def _build_verifier(settings: Settings):
    try:
        return build_verifier(settings)
    except RuntimeConfigError as exc:
        _fail(str(exc), exc.hint)


@app.callback()
def main(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="enable debug logging"),
) -> None:
    settings = Settings()
    _configure_logging("DEBUG" if verbose else settings.log_level)
    ctx.obj = settings


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(f"yinju {__version__}")


@app.command()
def serve(
    ctx: typer.Context,
    host: str | None = typer.Option(None, "--host", help="bind address (default 127.0.0.1)"),
    port: int | None = typer.Option(None, "--port", min=1, max=65535),
) -> None:
    """Serve the local web workbench and API."""
    import uvicorn

    from .api import create_app

    settings: Settings = ctx.obj
    uvicorn.run(
        create_app(settings),
        host=host or settings.web_host,
        port=port or settings.web_port,
        log_level=settings.log_level.lower(),
    )


@app.command()
def doctor(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="machine-readable output"),
) -> None:
    """Check seekdb, PowerContext, data dir, and provider settings."""
    settings: Settings = ctx.obj
    checks = run_checks(settings)
    if as_json:
        typer.echo(json.dumps([check.to_dict() for check in checks], ensure_ascii=False, indent=2))
    else:
        for check in checks:
            mark = "OK  " if check.ok else "FAIL"
            typer.echo(f"[{mark}] {check.name:<13} {check.detail}")
            if check.hint:
                typer.echo(f"       hint: {check.hint}")
    if not all(check.ok for check in checks):
        raise typer.Exit(code=1)


@app.command()
def ingest(
    ctx: typer.Context,
    bib: Path = typer.Option(  # noqa: B008 - Typer requires option calls in defaults
        Path("data/samples/bib.json"),
        "--bib",
        exists=True,
        dir_okay=False,
        help="bibliography JSON mapping paper keys to PDFs",
    ),
    key: list[str] | None = typer.Option(  # noqa: B008 - Typer requires option calls in defaults
        None, "--key", help="ingest only this key (repeatable)"
    ),
    force: bool = typer.Option(False, "--force", help="re-parse and re-index even if unchanged"),
    batch_size: int = typer.Option(64, "--batch-size", min=1, max=256),
    as_json: bool = typer.Option(False, "--json", help="machine-readable output"),
) -> None:
    """Parse PDFs, embed evidence units, and store them in seekdb."""
    settings: Settings = ctx.obj
    try:
        refs = load_bibliography(bib)
    except BibliographyError as exc:
        _fail(str(exc), "see data/samples/bib.json for the expected shape")

    embedder = _build_embedder(settings)
    store = _open_store(settings, embedder)
    cache = _open_cache(settings, embedder)

    def on_progress(paper_key: str, done: int, total: int) -> None:
        if not as_json:
            typer.echo(f"  {paper_key}: embedded {done}/{total}", err=True)

    try:
        results = ingest_bibliography(
            refs,
            store,
            cache,
            keys=key,
            force=force,
            batch_size=batch_size,
            on_progress=on_progress,
        )
    except KeyError as exc:
        _fail(str(exc.args[0]))

    if as_json:
        typer.echo(json.dumps([result.to_dict() for result in results], ensure_ascii=False, indent=2))
    else:
        for result in results:
            _echo_ingest_result(result)
        _echo_ingest_summary(results)
    if any(result.status == "failed" for result in results):
        raise typer.Exit(code=1)


@app.command()
def papers(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="machine-readable output"),
) -> None:
    """List ingested papers from the seekdb registry."""
    settings: Settings = ctx.obj
    embedder = _build_embedder(settings) if settings.embedding_provider == "local" else None
    store = _open_store(settings, embedder)
    records = store.list_papers()
    if as_json:
        typer.echo(json.dumps([asdict(record) for record in records], ensure_ascii=False, indent=2))
        return
    if not records:
        typer.echo("no papers ingested yet; run: yinju ingest --bib data/samples/bib.json")
        return
    typer.echo(
        f"{'KEY':<16} {'PAGES':>5} {'PARA':>5} {'SENT':>5} {'UNITS':>6} "
        f"{'INGESTED':<27} TITLE"
    )
    for record in records:
        typer.echo(
            f"{record.paper_key:<16} {record.page_count:>5} {record.para_count:>5} "
            f"{record.sent_count:>5} {record.para_count + record.sent_count:>6} "
            f"{record.ingested_at:<27} {record.title}"
        )


@app.command()
def search(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="claim or query text"),
    paper_key: str = typer.Option(..., "--paper-key", help="restrict retrieval to this paper"),
    unit_type: str = typer.Option("sent", "--unit-type", help="sent or para"),
    mode: str = typer.Option("hybrid", "--mode", help="hybrid (fulltext + vector RRF) or vector"),
    limit: int = typer.Option(5, "--limit", min=1, max=50),
    as_json: bool = typer.Option(False, "--json", help="machine-readable output"),
) -> None:
    """Search evidence inside one paper with hybrid RRF or vector-only retrieval."""
    settings: Settings = ctx.obj
    if unit_type not in {"sent", "para"}:
        _fail("--unit-type must be 'sent' or 'para'")
    if mode not in {"hybrid", "vector"}:
        _fail("--mode must be 'hybrid' or 'vector'")
    embedder = _build_embedder(settings)
    store = _open_store(settings, embedder)
    keywords = extract_keywords(query)
    try:
        if mode == "hybrid":
            query_vector = _open_cache(settings, embedder).embed([query]).vectors[0]
            hits = store.hybrid_search(
                query_vector,
                keywords,
                paper_key,
                unit_type=unit_type,
                limit=limit,
            )
        else:
            hits = store.search(query, paper_key, unit_type=unit_type, limit=limit)
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports query failures
        _fail(f"search failed: {type(exc).__name__}: {exc}")

    if as_json:
        payload = {
            "query": query,
            "paper_key": paper_key,
            "unit_type": unit_type,
            "mode": mode,
            "keywords": list(keywords) if mode == "hybrid" else [],
            "rrf_rank_constant": RRF_RANK_CONSTANT if mode == "hybrid" else None,
            "hits": [asdict(hit) for hit in hits],
        }
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(
        f"paper={paper_key} unit={unit_type} mode={mode} hits={len(hits)} "
        f"keywords={' '.join(keywords) if mode == 'hybrid' else '-'}"
    )
    if mode == "hybrid":
        for hit in hits:
            typer.echo(
                f"{hit.rrf_score:.4f}  p{hit.page:<3} {hit.unit_id:<32} "
                f"ft={_rank(hit.fulltext_rank)} vec={_rank(hit.vector_rank)} {hit.text}"
            )
    else:
        for hit in hits:
            typer.echo(f"{hit.distance:.4f}  p{hit.page:<3} {hit.unit_id:<32} {hit.text}")


@app.command()
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
        _fail(str(exc), "see data/samples/draft.md and data/samples/bib.json")

    cited = {citation for claim in claims for citation in claim.citations}
    unknown = sorted(cited - refs.keys())
    if unknown:
        _fail(
            "draft cites keys missing from bibliography: " + ", ".join(unknown),
            f"add them to {bib}",
        )

    embedder = _build_embedder(settings)
    store = _open_store(settings, embedder)
    cache = _open_cache(settings, embedder)
    verifier = _build_verifier(settings)
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
        _fail(str(exc))
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports audit failures
        _fail(f"audit failed: {type(exc).__name__}: {exc}")

    try:
        files = write_reports(report, out)
    except OSError as exc:
        _fail(f"cannot write report: {exc}", f"check permissions for {out}")

    memory_payload = _sync_memory(settings, report, bib, memory)

    if as_json:
        payload = report_to_dict(report)
        payload["files"] = {kind: str(path) for kind, path in files.items()}
        payload["memory"] = memory_payload
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        _echo_audit_summary(report, files, err=True)
        _echo_memory_summary(memory_payload, err=True)
    else:
        _echo_audit_summary(report, files, err=False)
        _echo_memory_summary(memory_payload, err=False)
    if report.error_count:
        raise typer.Exit(code=1)


@app.command("eval")
def evaluate_labels(
    ctx: typer.Context,
    labels: Path = typer.Option(  # noqa: B008 - Typer requires option calls in defaults
        Path("data/samples/labels.json"),
        "--labels",
        exists=True,
        dir_okay=False,
        help="labeled citation set with expected verdicts and evidence pages",
    ),
    bib: Path = typer.Option(  # noqa: B008 - Typer requires option calls in defaults
        Path("data/samples/bib.json"),
        "--bib",
        exists=True,
        dir_okay=False,
        help="bibliography JSON mapping paper keys to PDFs",
    ),
    out: Path = typer.Option(  # noqa: B008 - Typer requires option calls in defaults
        Path("data/runtime/eval"),
        "--out",
        help="directory for <dataset>.md and <dataset>.json",
    ),
    paragraphs: int = typer.Option(5, "--paragraphs", min=1, max=10),
    per_leg: int = typer.Option(20, "--per-leg", min=1, max=100),
    as_json: bool = typer.Option(False, "--json", help="print full evaluation JSON to stdout"),
) -> None:
    """Score the configured verifier on a labeled citation set."""
    settings: Settings = ctx.obj
    try:
        label_set = load_labeled_set(labels)
        refs = load_bibliography(bib)
    except (LabelError, BibliographyError) as exc:
        _fail(str(exc), "see data/samples/labels.json and data/samples/bib.json")

    embedder = _build_embedder(settings)
    store = _open_store(settings, embedder)
    cache = _open_cache(settings, embedder)
    verifier = _build_verifier(settings)
    engine = AuditEngine(
        store,
        cache,
        verifier,
        embedding_model=embedding_model_id(embedder),
        paragraph_limit=paragraphs,
        per_leg=per_leg,
    )
    try:
        report = evaluate(engine, label_set, refs, str(bib))
    except LabelError as exc:
        _fail(str(exc))
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports evaluation failures
        _fail(f"evaluation failed: {type(exc).__name__}: {exc}")

    try:
        files = write_evaluation(report, out)
    except OSError as exc:
        _fail(f"cannot write evaluation: {exc}", f"check permissions for {out}")

    if as_json:
        payload = evaluation_to_dict(report)
        payload["files"] = {kind: str(path) for kind, path in files.items()}
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        _echo_evaluation_summary(report, files, err=True)
    else:
        _echo_evaluation_summary(report, files, err=False)
    if report.metrics["errors"]:
        raise typer.Exit(code=1)


def _echo_evaluation_summary(
    report: EvaluationReport,
    files: dict[str, Path],
    err: bool = False,
) -> None:
    metrics = report.metrics
    typer.echo(
        f"eval: dataset={report.dataset} items={metrics['total']} | "
        f"labels supported={metrics['labels']['supported']} "
        f"unsupported={metrics['labels']['unsupported']} | "
        f"unsupported recall={_fmt_ratio(metrics['unsupported_recall'])} "
        f"precision={_fmt_ratio(metrics['unsupported_precision'])} | "
        f"handled={_fmt_ratio(metrics['unsupported_handled_rate'])} "
        f"auto-pass={metrics['unsupported_auto_pass']} | "
        f"review={_fmt_ratio(metrics['review_rate'])} | "
        f"evidence-page hit={_fmt_ratio(metrics['evidence_page_hit_rate'])} | "
        f"errors={metrics['errors']}",
        err=err,
    )
    for kind in ("markdown", "json"):
        typer.echo(f"{kind}: {files[kind]}", err=err)


def _fmt_ratio(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def _sync_memory(
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


def _echo_memory_summary(memory: dict[str, object], err: bool) -> None:
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


def _echo_ingest_result(result: IngestResult) -> None:
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


def _echo_ingest_summary(results: list[IngestResult]) -> None:
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


def _rank(rank: int | None) -> str:
    return str(rank) if rank is not None else "-"


def _echo_audit_summary(
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
