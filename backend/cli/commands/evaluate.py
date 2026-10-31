from __future__ import annotations

import json
from pathlib import Path

import typer

from ...audit import (
    AuditEngine,
    LabelError,
    evaluate,
    evaluation_to_dict,
    load_labeled_set,
    write_evaluation,
)
from ...core import Settings
from ...evidence import (
    BibliographyError,
    embedding_model_id,
    load_bibliography,
)
from ..deps import (
    fail,
    require_cache,
    require_embedder,
    require_store,
    require_verifier,
)
from ..output import echo_evaluation_summary


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
        fail(str(exc), "see data/samples/labels.json and data/samples/bib.json")

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
        report = evaluate(engine, label_set, refs, str(bib))
    except LabelError as exc:
        fail(str(exc))
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports evaluation failures
        fail(f"evaluation failed: {type(exc).__name__}: {exc}")

    try:
        files = write_evaluation(report, out)
    except OSError as exc:
        fail(f"cannot write evaluation: {exc}", f"check permissions for {out}")

    if as_json:
        payload = evaluation_to_dict(report)
        payload["files"] = {kind: str(path) for kind, path in files.items()}
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        echo_evaluation_summary(report, files, err=True)
    else:
        echo_evaluation_summary(report, files, err=False)
    if report.metrics["errors"]:
        raise typer.Exit(code=1)


def register(app: typer.Typer) -> None:
    app.command("eval")(evaluate_labels)
