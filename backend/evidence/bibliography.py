from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

KEY_PATTERN = re.compile(r"^[A-Za-z0-9_:\-]+$")


class BibliographyError(ValueError):
    pass


@dataclass(frozen=True)
class PaperRef:
    key: str
    file: Path
    title: str = ""
    authors: str = ""
    year: int | None = None
    source_url: str = ""


def load_bibliography(path: Path) -> dict[str, PaperRef]:
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicates)
    except OSError as exc:
        raise BibliographyError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise BibliographyError(f"invalid JSON in {path}: {exc}") from exc

    if not isinstance(payload, dict) or not payload:
        raise BibliographyError(f"{path} must contain a non-empty object of paper key -> PDF")

    base = path.parent
    refs: dict[str, PaperRef] = {}
    for raw_key, value in payload.items():
        key = str(raw_key)
        _validate_key(key)
        if isinstance(value, str):
            relative = value
            metadata: dict = {}
        elif isinstance(value, dict):
            relative = value.get("file", "")
            metadata = value
        else:
            raise BibliographyError(f"{key}: expected a path string or an object with 'file'")
        if not isinstance(relative, str) or not relative.strip():
            raise BibliographyError(f"{key}: missing 'file'")

        file = (base / relative).resolve()
        if not file.is_file():
            raise BibliographyError(f"{key}: PDF not found: {file}")
        if file.suffix.lower() != ".pdf":
            raise BibliographyError(f"{key}: not a PDF: {file}")

        title = _string(metadata.get("title", ""), key, "title")
        authors = _string(metadata.get("authors", ""), key, "authors")
        source_url = _string(metadata.get("source_url", ""), key, "source_url")
        year = _year(metadata.get("year"), key)
        refs[key] = PaperRef(
            key=key,
            file=file,
            title=title,
            authors=authors,
            year=year,
            source_url=source_url,
        )

    return dict(sorted(refs.items()))


def _validate_key(key: str) -> None:
    if not KEY_PATTERN.match(key):
        raise BibliographyError(
            f"invalid paper key {key!r}; use letters, digits, underscore, colon, or hyphen"
        )


def _string(value: object, key: str, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise BibliographyError(f"{key}: '{field}' must be a string")
    return value.strip()


def _year(value: object, key: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1000 <= value <= 3000:
        raise BibliographyError(f"{key}: 'year' must be an integer between 1000 and 3000")
    return value


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise BibliographyError(f"duplicate key {key!r} in bibliography")
        result[key] = value
    return result
