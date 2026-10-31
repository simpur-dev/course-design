from __future__ import annotations

import json
from dataclasses import asdict

import typer

from ...audit import extract_keywords
from ...core import Settings
from ...evidence import RRF_RANK_CONSTANT
from ..deps import fail, require_cache, require_embedder, require_store
from ..output import rank


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
        fail("--unit-type must be 'sent' or 'para'")
    if mode not in {"hybrid", "vector"}:
        fail("--mode must be 'hybrid' or 'vector'")
    embedder = require_embedder(settings)
    store = require_store(settings, embedder)
    keywords = extract_keywords(query)
    try:
        if mode == "hybrid":
            query_vector = require_cache(settings, embedder).embed([query]).vectors[0]
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
        fail(f"search failed: {type(exc).__name__}: {exc}")

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
                f"ft={rank(hit.fulltext_rank)} vec={rank(hit.vector_rank)} {hit.text}"
            )
    else:
        for hit in hits:
            typer.echo(f"{hit.distance:.4f}  p{hit.page:<3} {hit.unit_id:<32} {hit.text}")


def register(app: typer.Typer) -> None:
    app.command()(search)
