from __future__ import annotations

import typer

from ..core import Settings
from .commands import audit as audit_command
from .commands import doctor as doctor_command
from .commands import evaluate as evaluate_command
from .commands import ingest as ingest_command
from .commands import papers as papers_command
from .commands import search as search_command
from .commands import serve as serve_command
from .commands import version as version_command
from .deps import configure_logging

app = typer.Typer(help="引据 CitationProof CLI", no_args_is_help=True)


@app.callback()
def main(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="enable debug logging"),
) -> None:
    settings = Settings()
    configure_logging("DEBUG" if verbose else settings.log_level)
    ctx.obj = settings


version_command.register(app)
serve_command.register(app)
doctor_command.register(app)
ingest_command.register(app)
papers_command.register(app)
search_command.register(app)
audit_command.register(app)
evaluate_command.register(app)
