from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

MIN_SENTENCE_CHARS = 20
MAX_PARAGRAPH_CHARS = 750

UNIT_PARA = "para"
UNIT_SENT = "sent"

_SENTINEL = "\u2024"
_ABBREVIATIONS = (
    "e.g.",
    "i.e.",
    "et al.",
    "etc.",
    "vs.",
    "cf.",
    "approx.",
    "Fig.",
    "Figs.",
    "Eq.",
    "Eqs.",
    "Sec.",
    "Secs.",
    "Tab.",
    "Ref.",
    "Refs.",
    "No.",
    "Nos.",
    "Dr.",
    "Prof.",
)
_ABBREVIATION_RE = re.compile(
    r"\b(" + "|".join(re.escape(item.rstrip(".")) for item in _ABBREVIATIONS) + r")\.",
    re.IGNORECASE,
)
_DECIMAL_RE = re.compile(r"(?<=\d)\.(?=\d)")
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“”‘’(\[])")


class PdfParseError(ValueError):
    pass


@dataclass(frozen=True)
class EvidenceUnit:
    unit_id: str
    paper_key: str
    page: int
    unit_type: str
    unit_index: int
    parent_id: str
    text: str

    def to_metadata(self) -> dict[str, str | int]:
        return {
            "paper_key": self.paper_key,
            "page": self.page,
            "unit_type": self.unit_type,
            "unit_index": self.unit_index,
            "parent_id": self.parent_id,
        }


@dataclass(frozen=True)
class ParsedPaper:
    page_count: int
    units: tuple[EvidenceUnit, ...]

    @property
    def para_count(self) -> int:
        return sum(1 for unit in self.units if unit.unit_type == UNIT_PARA)

    @property
    def sent_count(self) -> int:
        return sum(1 for unit in self.units if unit.unit_type == UNIT_SENT)


def normalize_page_text(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\u00ad", "")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"-\n(?=[a-z])", "", text)
    text = re.sub(r"[\f\v]+", " ", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    protected = _ABBREVIATION_RE.sub(lambda match: match.group(0)[:-1] + _SENTINEL, text)
    protected = _DECIMAL_RE.sub(_SENTINEL, protected)
    parts = _SENTENCE_END_RE.split(protected)
    sentences = [part.replace(_SENTINEL, ".").strip() for part in parts]
    return [sentence for sentence in sentences if sentence]


def units_from_pages(pages: list[str], paper_key: str) -> tuple[EvidenceUnit, ...]:
    units: list[EvidenceUnit] = []
    for page_number, raw in enumerate(pages, start=1):
        page_text = normalize_page_text(raw)
        if not page_text:
            continue
        sentences = split_sentences(page_text)
        groups = _paragraph_groups(sentences)

        for para_index, group in enumerate(groups, start=1):
            units.append(
                EvidenceUnit(
                    unit_id=f"{paper_key}:p{page_number}:para{para_index}",
                    paper_key=paper_key,
                    page=page_number,
                    unit_type=UNIT_PARA,
                    unit_index=para_index,
                    parent_id="",
                    text=" ".join(group),
                )
            )

        sentence_index = 0
        for para_index, group in enumerate(groups, start=1):
            parent_id = f"{paper_key}:p{page_number}:para{para_index}"
            for sentence in group:
                sentence_index += 1
                if len(sentence) < MIN_SENTENCE_CHARS:
                    continue
                units.append(
                    EvidenceUnit(
                        unit_id=f"{paper_key}:p{page_number}:sent{sentence_index}",
                        paper_key=paper_key,
                        page=page_number,
                        unit_type=UNIT_SENT,
                        unit_index=sentence_index,
                        parent_id=parent_id,
                        text=sentence,
                    )
                )
    return tuple(units)


def _paragraph_groups(sentences: list[str]) -> list[list[str]]:
    groups: list[list[str]] = []
    current: list[str] = []
    current_chars = 0
    for sentence in sentences:
        addition = len(sentence) + (1 if current else 0)
        if current and current_chars + addition > MAX_PARAGRAPH_CHARS:
            groups.append(current)
            current = []
            current_chars = 0
            addition = len(sentence)
        current.append(sentence)
        current_chars += addition
    if current:
        groups.append(current)
    return groups


def parse_pdf(path: Path, paper_key: str) -> ParsedPaper:
    try:
        document = pymupdf.open(path)
    except Exception as exc:
        raise PdfParseError(f"cannot open {path.name}: {type(exc).__name__}: {exc}") from exc

    try:
        if document.needs_pass:
            raise PdfParseError(f"{path.name} is password protected")
        if document.page_count == 0:
            raise PdfParseError(f"{path.name} has no pages")
        pages = [document[number].get_text("text") for number in range(document.page_count)]
    finally:
        document.close()

    units = units_from_pages(pages, paper_key)
    if not units:
        raise PdfParseError(
            f"{path.name} has no extractable text; scanned PDFs require OCR, which is not supported"
        )
    return ParsedPaper(page_count=len(pages), units=units)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
