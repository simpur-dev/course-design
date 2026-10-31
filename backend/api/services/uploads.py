from __future__ import annotations

import hashlib
import os
import re
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import HTTPException, Request

from ...evidence import PaperRef
from .files import read_json, write_json_atomic

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
UPLOAD_ROOT = "uploads"
UPLOAD_BIB = "bib.json"
UPLOAD_PAPERS = "papers"


def too_large() -> HTTPException:
    limit = MAX_UPLOAD_BYTES // (1024 * 1024)
    return HTTPException(
        status_code=413,
        detail={
            "message": f"PDF 不能超过 {limit} MB",
            "hint": "请压缩或拆分 PDF 后再上传",
        },
    )


def declared_too_large(request: Request) -> bool:
    declared = request.headers.get("content-length", "")
    return declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES


async def read_limited_body(request: Request) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise too_large()
        chunks.append(chunk)
    if size == 0:
        raise HTTPException(status_code=400, detail={"message": "上传内容为空"})
    return b"".join(chunks)


def safe_upload_name(raw: str) -> str:
    name = PurePosixPath(raw.replace("\\", "/")).name
    if not name or name in {".", ".."} or "\x00" in name:
        raise HTTPException(
            status_code=400,
            detail={"message": "文件名不合法", "hint": "请使用常见的 PDF 文件名"},
        )
    return name[:200]


def upload_slug(stem: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return slug[:40].strip("-") or "paper"


def upload_key(entries: dict[str, Any], slug: str, digest: str) -> str:
    base = f"upload-{slug}"
    for length in (8, 12, 16, 32):
        candidate = f"{base}-{digest[:length]}"
        if candidate not in entries:
            return candidate
    return f"{base}-{uuid.uuid4().hex[:12]}"


def upload_root(data_root: Path) -> Path:
    return data_root / UPLOAD_ROOT


def upload_bib_path(data_root: Path) -> Path:
    return upload_root(data_root) / UPLOAD_BIB


def load_upload_bib(data_root: Path) -> dict[str, Any]:
    path = upload_bib_path(data_root)
    if not path.is_file():
        return {}
    payload = read_json(path)
    if payload is None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"{path} 无法解析",
                "hint": "修复或移除该文件后再上传",
            },
        )
    return payload


def find_duplicate(
    data_root: Path,
    entries: dict[str, Any],
    digest: str,
) -> tuple[str, PaperRef] | None:
    root = upload_root(data_root)
    for key, value in entries.items():
        if not isinstance(key, str):
            continue
        relative = value
        if isinstance(value, dict):
            relative = value.get("file")
        if not isinstance(relative, str) or not relative.strip():
            continue
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            continue
        if file_sha256(path) != digest:
            continue
        metadata = value if isinstance(value, dict) else {}
        year = metadata.get("year")
        return key, PaperRef(
            key=key,
            file=path,
            title=str(metadata.get("title") or ""),
            authors=str(metadata.get("authors") or ""),
            year=year if isinstance(year, int) and not isinstance(year, bool) else None,
            source_url=str(metadata.get("source_url") or ""),
        )
    return None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def store_upload(
    data_root: Path,
    entries: dict[str, Any],
    *,
    body: bytes,
    display: str,
    title: str,
    authors: str,
    year: int | None,
    key: str,
) -> PaperRef:
    papers_dir = upload_root(data_root) / UPLOAD_PAPERS
    papers_dir.mkdir(parents=True, exist_ok=True)
    target = papers_dir / f"{key}.pdf"
    tmp = papers_dir / f".{key}.{uuid.uuid4().hex}.tmp"
    tmp.write_bytes(body)
    os.replace(tmp, target)

    clean_title = (title.strip() or Path(display).stem)[:300]
    clean_authors = authors.strip()[:300]
    entry: dict[str, Any] = {
        "file": target.relative_to(upload_root(data_root)).as_posix(),
        "title": clean_title,
    }
    if clean_authors:
        entry["authors"] = clean_authors
    if year is not None:
        entry["year"] = year
    try:
        write_json_atomic(upload_bib_path(data_root), {**entries, key: entry})
    except OSError:
        target.unlink(missing_ok=True)
        raise
    return PaperRef(
        key=key,
        file=target,
        title=clean_title,
        authors=clean_authors,
        year=year,
    )


def upload_paper(data_root: Path, ref: PaperRef) -> dict[str, Any]:
    return {
        "key": ref.key,
        "title": ref.title or ref.file.stem,
        "authors": ref.authors,
        "year": ref.year,
        "file": ref.file.relative_to(data_root).as_posix(),
    }
