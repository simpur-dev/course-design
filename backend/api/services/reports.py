from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .files import read_json

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
DOWNLOADS = {
    "markdown": ("report.md", "text/markdown; charset=utf-8"),
    "csv": ("report.csv", "text/csv; charset=utf-8"),
    "json": ("report.json", "application/json"),
}


def report_dirs(reports_root: Path) -> list[Path]:
    if not reports_root.is_dir():
        return []
    directories = [
        path
        for path in reports_root.iterdir()
        if path.is_dir() and (path / "report.json").is_file()
    ]
    return sorted(directories, key=lambda path: path.name, reverse=True)


def find_report_dir(reports_root: Path, run_id: str) -> Path:
    if not RUN_ID_PATTERN.match(run_id):
        raise HTTPException(status_code=404, detail={"message": "报告不存在"})
    for directory in report_dirs(reports_root):
        payload = read_report(directory)
        if payload is not None and payload.get("run_id") == run_id:
            return directory
    raise HTTPException(status_code=404, detail={"message": "报告不存在"})


def read_report(directory: Path) -> dict[str, Any] | None:
    return read_json(directory / "report.json")


def report_summary(payload: dict[str, Any]) -> dict[str, Any]:
    run_id = str(payload.get("run_id", ""))
    return {
        "run_id": run_id,
        "generated_at": payload.get("generated_at"),
        "draft": payload.get("draft"),
        "bib": payload.get("bib"),
        "verifier": payload.get("verifier"),
        "summary": payload.get("summary", {}),
        "warnings": payload.get("warnings", []),
        "downloads": download_links(run_id),
    }


def download_links(run_id: str) -> dict[str, str]:
    return {kind: f"/api/reports/{run_id}/download/{kind}" for kind in DOWNLOADS}


def report_detail(reports_root: Path, run_id: str) -> dict[str, Any]:
    directory = find_report_dir(reports_root, run_id)
    payload = read_report(directory)
    if payload is None:
        raise HTTPException(status_code=404, detail={"message": "报告不存在"})
    payload["downloads"] = download_links(run_id)
    memory = read_json(directory / "memory.json")
    if memory is not None:
        payload["memory"] = memory
    return payload


def report_file(reports_root: Path, run_id: str, kind: str) -> tuple[Path, str, str]:
    if kind not in DOWNLOADS:
        raise HTTPException(status_code=404, detail={"message": "不支持的报告格式"})
    directory = find_report_dir(reports_root, run_id)
    filename, media_type = DOWNLOADS[kind]
    path = directory / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail={"message": f"报告文件缺失：{filename}"})
    return path, media_type, f"{run_id}-{filename}"
