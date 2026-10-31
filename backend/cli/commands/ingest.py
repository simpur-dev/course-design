from __future__ import annotations

import json
from pathlib import Path

import typer

from ...core import Settings
from ...evidence import BibliographyError, ingest_bibliography, load_bibliography
from ..deps import fail, require_cache, require_embedder, require_store
from ..output import echo_ingest_result, echo_ingest_summary


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
        fail(str(exc), "see data/samples/bib.json for the expected shape")

    embedder = require_embedder(settings)
    store = require_store(settings, embedder)
    cache = require_cache(settings, embedder)

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
        fail(str(exc.args[0]))

    if as_json:
        typer.echo(json.dumps([result.to_dict() for result in results], ensure_ascii=False, indent=2))
    else:
        for result in results:
            echo_ingest_result(result)
        echo_ingest_summary(results)
    if any(result.status == "failed" for result in results):
        raise typer.Exit(code=1)


def register(app: typer.Typer) -> None:
    app.command()(ingest)
