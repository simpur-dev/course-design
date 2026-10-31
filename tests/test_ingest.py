import pytest

from backend.evidence.bibliography import PaperRef
from backend.evidence.embeddings import EmbedResult
from backend.evidence.ingest import ingest_bibliography, ingest_paper
from backend.evidence.store import PaperRecord


class FakeStore:
    def __init__(self) -> None:
        self.papers: dict[str, PaperRecord] = {}
        self.replacements: dict[str, tuple[list, list]] = {}
        self.replace_calls = 0

    def get_paper(self, key: str) -> PaperRecord | None:
        return self.papers.get(key)

    def replace_units(self, key, units, vectors) -> None:
        assert len(units) == len(vectors)
        self.replacements[key] = (list(units), list(vectors))
        self.replace_calls += 1

    def upsert_paper(self, record: PaperRecord) -> None:
        self.papers[record.paper_key] = record


class FakeCache:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts, batch_size=64, on_progress=None) -> EmbedResult:
        self.calls.append(list(texts))
        if on_progress is not None:
            on_progress(len(texts), len(texts))
        return EmbedResult(
            vectors=tuple((0.0, 0.0) for _ in texts),
            embedded=len(texts),
            computed=len(texts),
            cached=0,
            batches=1,
        )


class FailingCache:
    def embed(self, texts, batch_size=64, on_progress=None) -> EmbedResult:
        raise RuntimeError("embedding backend down")


def _ref(path, key: str = "paper") -> PaperRef:
    return PaperRef(
        key=key,
        file=path,
        title="A Paper",
        authors="A. Author",
        year=2020,
        source_url="https://example.org/paper",
    )


def _texts() -> list[str]:
    return [
        "The Transformer relies entirely on attention mechanisms and dispenses with recurrence.",
        "It also removes recurrence from both the encoder and the decoder.",
    ]


def test_ingest_records_paper_and_units(tmp_path, make_pdf) -> None:
    path = tmp_path / "paper.pdf"
    make_pdf(path, [" ".join(_texts())])
    store = FakeStore()
    cache = FakeCache()

    result = ingest_paper(_ref(path), store, cache)

    assert result.status == "ingested"
    assert (result.page_count, result.para_count, result.sent_count) == (1, 1, 2)
    assert result.unit_count == 3
    assert result.embedded == 3
    record = store.papers["paper"]
    assert record.title == "A Paper"
    assert record.file_name == "paper.pdf"
    assert len(record.file_sha256) == 64
    assert record.unit_mode == "para+sent"
    units, vectors = store.replacements["paper"]
    assert len(units) == len(vectors) == 3


def test_ingest_skips_unchanged_paper(tmp_path, make_pdf) -> None:
    path = tmp_path / "paper.pdf"
    make_pdf(path, [" ".join(_texts())])
    store = FakeStore()
    cache = FakeCache()

    ingest_paper(_ref(path), store, cache)
    calls = len(cache.calls)
    result = ingest_paper(_ref(path), store, cache)

    assert result.status == "skipped"
    assert result.unit_count == 3
    assert len(cache.calls) == calls
    assert store.replace_calls == 1


def test_force_reindexes_unchanged_paper(tmp_path, make_pdf) -> None:
    path = tmp_path / "paper.pdf"
    make_pdf(path, [" ".join(_texts())])
    store = FakeStore()
    cache = FakeCache()

    ingest_paper(_ref(path), store, cache)
    result = ingest_paper(_ref(path), store, cache, force=True)

    assert result.status == "updated"
    assert store.replace_calls == 2
    assert len(cache.calls) == 2


def test_changed_pdf_is_reingested(tmp_path, make_pdf) -> None:
    path = tmp_path / "paper.pdf"
    make_pdf(path, [" ".join(_texts())])
    store = FakeStore()
    cache = FakeCache()
    first = ingest_paper(_ref(path), store, cache)
    assert first.status == "ingested"
    first_hash = store.papers["paper"].file_sha256

    make_pdf(path, [" ".join(_texts()), "A second page adds another long enough evidence sentence."])
    second = ingest_paper(_ref(path), store, cache)

    assert second.status == "updated"
    assert second.page_count == 2
    assert store.papers["paper"].file_sha256 != first_hash


def test_embedding_failure_keeps_previous_units(tmp_path, make_pdf) -> None:
    path = tmp_path / "paper.pdf"
    make_pdf(path, [" ".join(_texts())])
    store = FakeStore()

    ingest_paper(_ref(path), store, FakeCache())
    replacements = dict(store.replacements)
    make_pdf(path, ["A changed page with enough words to become a valid evidence sentence."])

    with pytest.raises(RuntimeError, match="embedding backend down"):
        ingest_paper(_ref(path), store, FailingCache())
    assert store.replacements == replacements


def test_bibliography_isolates_failures_and_reports_progress(tmp_path, make_pdf) -> None:
    path = tmp_path / "good.pdf"
    make_pdf(path, [" ".join(_texts())])
    refs = {
        "good": _ref(path, "good"),
        "missing": _ref(tmp_path / "missing.pdf", "missing"),
    }
    progress: list[tuple[str, int, int]] = []

    results = ingest_bibliography(
        refs,
        FakeStore(),
        FakeCache(),
        on_progress=lambda key, done, total: progress.append((key, done, total)),
    )

    statuses = {result.key: result.status for result in results}
    assert statuses == {"good": "ingested", "missing": "failed"}
    assert "FileNotFoundError" in next(result.error for result in results if result.key == "missing")
    assert progress == [("good", 3, 3)]


def test_bibliography_rejects_unknown_key(tmp_path) -> None:
    with pytest.raises(KeyError, match="unknown paper key"):
        ingest_bibliography({}, FakeStore(), FakeCache(), keys=["nope"])


def test_result_serializes_unit_count(tmp_path, make_pdf) -> None:
    path = tmp_path / "paper.pdf"
    make_pdf(path, [" ".join(_texts())])
    result = ingest_paper(_ref(path), FakeStore(), FakeCache())
    payload = result.to_dict()
    assert payload["unit_count"] == 3
    assert payload["status"] == "ingested"
