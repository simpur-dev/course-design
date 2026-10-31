from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ...evidence import BibliographyError, load_bibliography
from .files import timestamp

CITATION_MARK = re.compile(r"\[@[^\]]+\]")
DRAFT_PREVIEW_CHARS = 20000


def resolve_data_path(data_root: Path, raw: str, suffixes: set[str]) -> Path:
    if "\x00" in raw:
        raise HTTPException(status_code=400, detail={"message": "路径包含非法字符"})
    candidate = Path(raw)
    if not candidate.is_absolute():
        if candidate.parts and candidate.parts[0].lower() == data_root.name.lower():
            candidate = Path.cwd() / candidate
        else:
            candidate = data_root / candidate
    candidate = candidate.resolve()
    if not candidate.is_relative_to(data_root):
        raise HTTPException(
            status_code=400,
            detail={"message": "路径必须位于数据目录内"},
        )
    if candidate.suffix.lower() not in suffixes:
        allowed = ", ".join(sorted(suffixes))
        raise HTTPException(
            status_code=400,
            detail={"message": f"文件类型必须是以下之一：{allowed}"},
        )
    if not candidate.is_file():
        raise HTTPException(
            status_code=400,
            detail={"message": f"数据目录下找不到文件：{raw}"},
        )
    return candidate


def data_files(data_root: Path, suffix: str) -> list[Path]:
    files: list[Path] = []
    if not data_root.is_dir():
        return files
    for path in data_root.rglob(f"*{suffix}"):
        relative = path.relative_to(data_root)
        if "runtime" in relative.parts or not path.is_file():
            continue
        if path.stat().st_size > 1_000_000:
            continue
        files.append(path)
    return sorted(files, key=lambda path: path.relative_to(data_root).as_posix())


def bibliography_files(data_root: Path) -> list[Path]:
    usable: list[Path] = []
    for path in data_files(data_root, ".json"):
        try:
            load_bibliography(path)
        except BibliographyError:
            continue
        usable.append(path)
    return usable


def draft_listing(data_root: Path) -> list[dict[str, Any]]:
    items = []
    for path in data_files(data_root, ".md"):
        text = path.read_text(encoding="utf-8", errors="replace")
        items.append(
            {
                "path": path.relative_to(data_root).as_posix(),
                "name": path.stem,
                "content": text[:DRAFT_PREVIEW_CHARS],
                "line_count": len(text.splitlines()),
                "char_count": len(text),
                "citation_count": len(CITATION_MARK.findall(text)),
                "truncated": len(text) > DRAFT_PREVIEW_CHARS,
                "updated_at": timestamp(path),
            }
        )
    return items


def bibliography_listing(data_root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(data_root).as_posix(),
            "name": path.stem,
            "updated_at": timestamp(path),
        }
        for path in bibliography_files(data_root)
    ]
