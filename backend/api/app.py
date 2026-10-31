from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from .. import __version__
from ..agent import run_audit
from ..audit import ProgressCallback
from ..core import Settings
from ..runtime import IngestSpec, RunSpec, run_ingest
from .context import AppContext
from .routes import audits, frontend, library, memory, reports, system
from .services.reports import download_links

RUNNER = Callable[[Any, ProgressCallback], dict[str, Any]]


def create_app(
    settings: Settings | None = None,
    runner: RUNNER | None = None,
    ingest_runner: RUNNER | None = None,
) -> FastAPI:
    settings = settings or Settings()
    frontend_root = frontend.resolve_frontend_root(settings)
    context = AppContext.build(
        settings,
        frontend_root=frontend_root,
        audit_runner=runner or _pipeline_audit_runner(settings),
        ingest_runner=ingest_runner or _pipeline_ingest_runner(settings),
    )

    app = FastAPI(
        title="引据 CitationProof API",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.context = context
    app.state.settings = settings
    app.state.data_root = context.data_root
    app.state.reports_root = context.reports_root
    app.state.frontend_root = frontend_root
    app.state.jobs = context.audit_jobs
    app.state.upload_jobs = context.ingest_jobs

    for router in (
        system.router,
        library.router,
        audits.router,
        reports.router,
        memory.router,
    ):
        app.include_router(router)
    frontend.mount(app, frontend_root)
    return app


def _pipeline_audit_runner(settings: Settings) -> RUNNER:
    def run(spec: RunSpec, progress: ProgressCallback) -> dict[str, Any]:
        payload = run_audit(settings, spec, progress)
        run_id = str(payload.get("run_id", ""))
        if run_id:
            payload["downloads"] = download_links(run_id)
        return payload

    return run


def _pipeline_ingest_runner(settings: Settings) -> RUNNER:
    def run(spec: IngestSpec, progress: ProgressCallback) -> dict[str, Any]:
        return run_ingest(settings, spec, progress)

    return run


def main() -> None:
    import uvicorn

    settings = Settings()
    uvicorn.run(
        create_app(settings),
        host=settings.server_host,
        port=settings.server_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
