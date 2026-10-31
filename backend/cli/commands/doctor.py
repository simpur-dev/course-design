from __future__ import annotations

import json

import typer

from ...core import Settings
from ...diagnostics import run_checks


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


def register(app: typer.Typer) -> None:
    app.command()(doctor)
