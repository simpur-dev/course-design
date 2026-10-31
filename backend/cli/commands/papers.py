from __future__ import annotations

import json
from dataclasses import asdict

import typer

from ...core import Settings
from ..deps import require_embedder, require_store


def papers(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="machine-readable output"),
) -> None:
    """List ingested papers from the seekdb registry."""
    settings: Settings = ctx.obj
    embedder = require_embedder(settings) if settings.embedding_provider == "local" else None
    store = require_store(settings, embedder)
    records = store.list_papers()
    if as_json:
        typer.echo(json.dumps([asdict(record) for record in records], ensure_ascii=False, indent=2))
        return
    if not records:
        typer.echo("no papers ingested yet; run: citationproof ingest --bib data/samples/bib.json")
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


def register(app: typer.Typer) -> None:
    app.command()(papers)
