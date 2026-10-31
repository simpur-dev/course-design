import os
import uuid
from pathlib import Path

import pytest
from pyseekdb import AdminClient, DefaultEmbeddingFunction

from backend.audit import AuditEngine
from backend.audit.claims import Claim
from backend.audit.terms import extract_keywords
from backend.audit.verdicts import BaselineVerifier
from backend.core.config import Settings
from backend.evidence.bibliography import PaperRef
from backend.evidence.embeddings import EmbeddingCache, embedding_model_id
from backend.evidence.ingest import ingest_bibliography
from backend.evidence.store import EvidenceStore

pytestmark = pytest.mark.skipif(
    os.environ.get("APP_TEST_SEEKDB") != "1",
    reason="set APP_TEST_SEEKDB=1 (and APP_SEEKDB_PORT) to run seekdb integration tests",
)


def _ref(path: Path, key: str) -> PaperRef:
    return PaperRef(key=key, file=path, title=f"{key} paper", authors="Test Author", year=2026)


def test_hybrid_audit_stays_inside_cited_paper(tmp_path, make_pdf) -> None:
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

    database = f"cd_it_{uuid.uuid4().hex[:10]}"
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
        ingest_bibliography(refs, store, cache)

        query = "beta corpus contains three billion tokens collected from web text"
        vector = cache.embed([query]).vectors[0]
        hits = store.hybrid_search(
            vector,
            extract_keywords(query),
            "alpha",
            unit_type="para",
            limit=5,
        )
        assert hits
        assert all(hit.paper_key == "alpha" for hit in hits)
        assert all(hit.unit_id.startswith("alpha:") for hit in hits)
        assert any(hit.fulltext_rank is not None or hit.vector_rank is not None for hit in hits)

        claims = [
            Claim(
                claim_id="claim-01",
                line_start=1,
                line_end=1,
                text="Alpha uses dense vectors to match paraphrased questions with supporting evidence.",
                citations=("alpha",),
            ),
            Claim(
                claim_id="claim-02",
                line_start=3,
                line_end=3,
                text="The beta corpus contains three billion tokens collected from web text.",
                citations=("alpha",),
            ),
        ]
        report = AuditEngine(
            store,
            cache,
            BaselineVerifier(),
            embedding_model_id(embedder),
            paragraph_limit=5,
        ).audit(claims, refs, "draft.md", "bib.json")

        assert report.error_count == 0
        assert report.citation_count == 2
        evidence_claim = report.claims[0].checks[0]
        assert evidence_claim.evidence is not None
        assert evidence_claim.evidence.paper_key == "alpha"
        assert evidence_claim.evidence.unit_id.startswith("alpha:")
        assert evidence_claim.verdict in {"partial", "unsupported", "unknown"}

        misattributed = report.claims[1].checks[0]
        assert misattributed.verdict in {"unsupported", "unknown"}
        assert misattributed.evidence is not None
        assert misattributed.evidence.paper_key == "alpha"
        assert misattributed.evidence.unit_id.startswith("alpha:")
        assert all(
            candidate.paper_key == "alpha" for candidate in misattributed.sentence_candidates
        )
        assert all(
            hit.paper_key == "alpha" for hit in misattributed.paragraph_hits
        )
    finally:
        if database in {item.name for item in admin.list_databases()}:
            admin.delete_database(database)
