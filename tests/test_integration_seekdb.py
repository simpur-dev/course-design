import os
import uuid
from pathlib import Path

import pytest
from pyseekdb import AdminClient, DefaultEmbeddingFunction

from yinju.bibliography import PaperRef
from yinju.config import Settings
from yinju.embeddings import EmbeddingCache
from yinju.ingest import ingest_bibliography
from yinju.store import EvidenceStore

pytestmark = pytest.mark.skipif(
    os.environ.get("YINJU_TEST_SEEKDB") != "1",
    reason="set YINJU_TEST_SEEKDB=1 (and YINJU_SEEKDB_PORT) to run seekdb integration tests",
)


def _ref(path: Path, key: str) -> PaperRef:
    return PaperRef(key=key, file=path, title=f"{key} paper", authors="Test Author", year=2026)


def test_ingest_filter_and_embedding_cache(tmp_path, make_pdf) -> None:
    alpha = tmp_path / "alpha.pdf"
    beta = tmp_path / "beta.pdf"
    make_pdf(
        alpha,
        [
            "Alpha retrieval uses dense vectors to match paraphrased questions with supporting evidence.",
            "The alpha model reaches ninety percent accuracy on the internal benchmark.",
        ],
    )
    make_pdf(
        beta,
        [
            "Beta decoding relies on a bidirectional encoder and masked language modeling.",
            "The beta corpus contains three billion tokens collected from web text.",
        ],
    )
    refs = {"alpha": _ref(alpha, "alpha"), "beta": _ref(beta, "beta")}

    database = f"yinju_it_{uuid.uuid4().hex[:10]}"
    settings = Settings(seekdb_database=database, _env_file=None)
    admin = AdminClient(
        host=settings.seekdb_host,
        port=settings.seekdb_port,
        user=settings.seekdb_user,
        password=settings.seekdb_password.get_secret_value(),
    )

    try:
        embedder = DefaultEmbeddingFunction()
        cache = EmbeddingCache(tmp_path / "cache.sqlite3", embedder)
        store = EvidenceStore(settings, embedder).ensure()

        first = ingest_bibliography(refs, store, cache)
        assert {result.status for result in first} == {"ingested"}
        assert all(result.unit_count == 4 for result in first)
        assert all(result.embedded == 4 and result.computed == 2 for result in first)

        record = store.get_paper("alpha")
        assert record is not None
        assert (record.page_count, record.para_count, record.sent_count) == (2, 2, 2)
        assert record.unit_mode == "para+sent"
        assert [paper.paper_key for paper in store.list_papers()] == ["alpha", "beta"]

        hits = store.search("dense vectors for paraphrased questions", "alpha", "sent", 3)
        assert hits
        assert all(hit.paper_key == "alpha" for hit in hits)
        assert any(hit.page == 1 for hit in hits)

        leak_check = store.search("three billion tokens collected from web text", "alpha", "sent", 3)
        assert leak_check
        assert all(hit.paper_key == "alpha" for hit in leak_check)
        assert all(not hit.unit_id.startswith("beta") for hit in leak_check)

        page_filtered = store.collection.query(
            query_texts=["accuracy benchmark"],
            n_results=5,
            where={"paper_key": {"$eq": "alpha"}, "page": {"$eq": 2}},
            include=["metadatas"],
        )
        assert page_filtered["ids"][0]
        assert all(
            metadata["paper_key"] == "alpha" and metadata["page"] == 2
            for metadata in page_filtered["metadatas"][0]
        )

        second = ingest_bibliography(refs, store, cache)
        assert {result.status for result in second} == {"skipped"}

        forced = ingest_bibliography(refs, store, cache, force=True)
        assert {result.status for result in forced} == {"updated"}
        assert all(result.embedded == 0 for result in forced)
        assert all(result.cached == result.unit_count for result in forced)
    finally:
        if database in {item.name for item in admin.list_databases()}:
            admin.delete_database(database)
