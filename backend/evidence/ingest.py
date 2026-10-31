from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from .bibliography import PaperRef
from .embeddings import EmbeddingCache
from .store import UNIT_MODE, EvidenceStore, PaperRecord
from .units import file_sha256, parse_pdf

ProgressHandler = Callable[[str, int, int], None]


@dataclass(frozen=True)
class IngestResult:
    key: str
    status: str
    page_count: int = 0
    para_count: int = 0
    sent_count: int = 0
    embedded: int = 0
    computed: int = 0
    cached: int = 0
    batches: int = 0
    seconds: float = 0.0
    error: str = ""

    @property
    def unit_count(self) -> int:
        return self.para_count + self.sent_count

    def to_dict(self) -> dict:
        return {**asdict(self), "unit_count": self.unit_count}


def ingest_paper(
    ref: PaperRef,
    store: EvidenceStore,
    cache: EmbeddingCache,
    force: bool = False,
    batch_size: int = 64,
    on_progress: Callable[[int, int], None] | None = None,
) -> IngestResult:
    started = time.perf_counter()
    digest = file_sha256(ref.file)
    existing = store.get_paper(ref.key)

    if (
        existing is not None
        and not force
        and existing.file_sha256 == digest
        and existing.unit_mode == UNIT_MODE
    ):
        return IngestResult(
            key=ref.key,
            status="skipped",
            page_count=existing.page_count,
            para_count=existing.para_count,
            sent_count=existing.sent_count,
            seconds=round(time.perf_counter() - started, 3),
        )

    parsed = parse_pdf(ref.file, ref.key)
    texts = [unit.text for unit in parsed.units]
    embeddings = cache.embed(texts, batch_size=batch_size, on_progress=on_progress)

    store.replace_units(ref.key, parsed.units, embeddings.vectors)
    record = PaperRecord(
        paper_key=ref.key,
        title=ref.title or ref.file.stem,
        authors=ref.authors,
        year=ref.year,
        source_url=ref.source_url,
        file_name=ref.file.name,
        file_sha256=digest,
        page_count=parsed.page_count,
        para_count=parsed.para_count,
        sent_count=parsed.sent_count,
        unit_mode=UNIT_MODE,
        ingested_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    store.upsert_paper(record)

    return IngestResult(
        key=ref.key,
        status="updated" if existing is not None else "ingested",
        page_count=parsed.page_count,
        para_count=parsed.para_count,
        sent_count=parsed.sent_count,
        embedded=embeddings.embedded,
        computed=embeddings.computed,
        cached=embeddings.cached,
        batches=embeddings.batches,
        seconds=round(time.perf_counter() - started, 3),
    )


def ingest_bibliography(
    refs: dict[str, PaperRef],
    store: EvidenceStore,
    cache: EmbeddingCache,
    keys: Sequence[str] | None = None,
    force: bool = False,
    batch_size: int = 64,
    on_progress: ProgressHandler | None = None,
) -> list[IngestResult]:
    selected = dict(refs)
    if keys:
        unknown = sorted(set(keys) - set(refs))
        if unknown:
            raise KeyError(f"unknown paper key(s): {', '.join(unknown)}")
        selected = {key: refs[key] for key in refs if key in set(keys)}

    results: list[IngestResult] = []
    for key, ref in selected.items():
        started = time.perf_counter()
        try:
            handler = (
                (lambda done, total, paper_key=key: on_progress(paper_key, done, total))
                if on_progress is not None
                else None
            )
            result = ingest_paper(
                ref,
                store,
                cache,
                force=force,
                batch_size=batch_size,
                on_progress=handler,
            )
        except Exception as exc:  # noqa: BLE001 - one bad paper must not stop the batch
            result = IngestResult(
                key=key,
                status="failed",
                seconds=round(time.perf_counter() - started, 3),
                error=f"{type(exc).__name__}: {exc}",
            )
        results.append(result)
    return results
