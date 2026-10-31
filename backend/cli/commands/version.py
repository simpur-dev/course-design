from __future__ import annotations

import typer

from ... import __version__


def version() -> None:
    """Print the installed version."""
    typer.echo(f"citationproof {__version__}")


def register(app: typer.Typer) -> None:
    app.command()(version)
