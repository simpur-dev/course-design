from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .bibliography import KEY_PATTERN

_CITATION_BLOCK = re.compile(r"\[([^\]]*@[^\]]*)\]")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s")
_FENCE = re.compile(r"^\s*(```|~~~)")
_LIST_MARKER = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+")
_BLOCKQUOTE = re.compile(r"^\s{0,3}>\s?")


class DraftError(ValueError):
    pass


@dataclass(frozen=True)
class Claim:
    claim_id: str
    line_start: int
    line_end: int
    text: str
    citations: tuple[str, ...]


def parse_draft(path: Path) -> list[Claim]:
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DraftError(f"cannot read {path}: {exc}") from exc
    if not raw.strip():
        raise DraftError(f"{path} is empty")

    claims: list[Claim] = []
    in_fence = False
    block: list[tuple[int, str]] = []
    block_kind = "normal"

    def flush() -> None:
        if not block:
            return
        lines = block.copy()
        block.clear()
        claim = _claim_from_block(lines, len(claims) + 1, path)
        if claim is not None:
            claims.append(claim)

    for number, line in enumerate(raw.splitlines(), start=1):
        if _FENCE.match(line):
            flush()
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not line.strip():
            flush()
            continue
        if _HEADING.match(line):
            flush()
            continue
        if _BLOCKQUOTE.match(line):
            kind = "quote"
        elif _LIST_MARKER.match(line):
            kind = "list"
        else:
            kind = "normal"
        if block and (
            kind == "list"
            or (kind == "quote" and block_kind != "quote")
            or (kind != "quote" and block_kind == "quote")
        ):
            flush()
        if not block:
            block_kind = kind
        block.append((number, _clean_markdown_line(line)))
    flush()

    if not claims:
        raise DraftError(f"no claims with [@key] citations found in {path}")
    return claims


def _clean_markdown_line(line: str) -> str:
    line = _BLOCKQUOTE.sub("", line)
    line = _LIST_MARKER.sub("", line)
    return line.strip()


def _claim_from_block(lines: list[tuple[int, str]], ordinal: int, path: Path) -> Claim | None:
    text = " ".join(part for _, part in lines if part)
    matches = list(_CITATION_BLOCK.finditer(text))
    if not matches:
        return None

    citations: list[str] = []
    for match in matches:
        for key in _parse_citation(match.group(1), lines[0][0], path):
            if key not in citations:
                citations.append(key)

    claim_text = _CITATION_BLOCK.sub("", text)
    claim_text = re.sub(r"\s+", " ", claim_text).strip()
    claim_text = re.sub(r"\s+([,.;:!?])", r"\1", claim_text)
    if len(claim_text) < 10:
        raise DraftError(
            f"{path}:{lines[0][0]}: claim text is too short after removing citations"
        )
    return Claim(
        claim_id=f"claim-{ordinal:02d}",
        line_start=lines[0][0],
        line_end=lines[-1][0],
        text=claim_text,
        citations=tuple(citations),
    )


def _parse_citation(inner: str, line_number: int, path: Path) -> list[str]:
    keys: list[str] = []
    for segment in re.split(r"[;,]", inner):
        key = segment.strip()
        if key.startswith("@"):
            key = key[1:].strip()
        if not key:
            raise DraftError(f"{path}:{line_number}: empty citation key")
        if not KEY_PATTERN.match(key):
            raise DraftError(
                f"{path}:{line_number}: unsupported citation {segment.strip()!r}; "
                "use [@key] or [@key1; @key2]"
            )
        keys.append(key)
    if not keys:
        raise DraftError(f"{path}:{line_number}: citation has no key")
    return keys
