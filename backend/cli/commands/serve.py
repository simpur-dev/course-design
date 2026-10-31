from __future__ import annotations

import typer

from ...core import Settings


def serve(
    ctx: typer.Context,
    host: str | None = typer.Option(None, "--host", help="bind address (default 127.0.0.1)"),
    port: int | None = typer.Option(None, "--port", min=1, max=65535),
) -> None:
    """Serve the local web workbench and API."""
    import uvicorn

    from ...api import create_app

    settings: Settings = ctx.obj
    uvicorn.run(
        create_app(settings),
        host=host or settings.server_host,
        port=port or settings.server_port,
        log_level=settings.log_level.lower(),
    )


def register(app: typer.Typer) -> None:
    app.command()(serve)
