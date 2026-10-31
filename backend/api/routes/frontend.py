from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ...core import Settings


def resolve_frontend_root(settings: Settings) -> Path | None:
    candidate = Path(settings.frontend_dir)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    candidate = candidate.resolve()
    return candidate if (candidate / "index.html").is_file() else None


def mount(app: FastAPI, frontend_root: Path | None) -> None:
    if frontend_root is not None:
        assets = frontend_root / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend(full_path: str) -> Any:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail={"message": "接口不存在"})
        if frontend_root is None:
            return JSONResponse(
                status_code=404,
                content={
                    "message": "前端尚未构建",
                    "hint": "先执行 npm --prefix frontend install && npm --prefix frontend run build",
                },
            )
        candidate = (frontend_root / full_path).resolve()
        if full_path and candidate.is_relative_to(frontend_root) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(frontend_root / "index.html")
