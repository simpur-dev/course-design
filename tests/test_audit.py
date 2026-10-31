from pathlib import Path

import pytest

from yinju.audit import AuditEngine, AuditError
from yinju.bibliography import PaperRef
from yinju.claims import Claim
from yinju.embeddings import EmbedResult
from yinju.store import HybridHit, PaperRecord, UnitRow
from yinju.verdicts import Verdict


class FakeCache:
    def __init__(self, vector=(1.0, 0.0)) -> None:
        self.vector = vector
        self.texts: list[str] = []

    def embed(self, texts, batch_size=64, on_progress=None):
        self.texts.extend(texts)
        return EmbedResult(
            vectors=tuple(self.vector for _ in texts),
            embedded=len(texts),
            computed=len(texts),
            cached=0,
            batches=1,
        )


class FakeStore:
    def __init__(self, papers, paragraph_hits, children, units=None, fail_keys=()):
        self.papers = papers
        self.paragraph_hits = paragraph_hits
        self.children = children
        self.units = units or {}
        self.fail_keys = set(fail_keys)
        self.search_calls = []

    def get_paper(self, paper_key):
        return self.papers.get(paper_key)

    def hybrid_search(self, query_embedding, keywords, paper_key, **kwargs):
        self.search_calls.append((paper_key, keywords, kwargs))
        if paper_key in self.fail_keys:
            raise RuntimeError(f"{paper_key} search broke")
        return list(self.paragraph_hits.get(paper_key, []))

    def fetch_children(self, paper_key, parent_ids, unit_type="sent", limit=1000):
        return [row for row in self.children if row.parent_id in parent_ids]

    def fetch_units(self, unit_ids):
        return [self.units[unit_id] for unit_id in unit_ids if unit_id in self.units]


class FixedVerifier:
    name = "test/fixed"

    def __init__(self, verdicts):
        self.verdicts = verdicts
        self.calls = {}

    def verify(self, claim, paper_key, paper_title, candidates):
        self.calls[paper_key] = list(candidates)
        verdict = self.verdicts.get(paper_key, "unknown")
        return Verdict(
            verdict=verdict,
            confidence="medium",
            review_required=verdict in {"partial", "unknown"},
            reason=f"{paper_key}:{verdict}",
            evidence=candidates[0] if candidates else None,
        )


def _paper(key: str) -> PaperRecord:
    return PaperRecord(
        paper_key=key,
        title=f"{key} title",
        authors="Author",
        year=2026,
        source_url="",
        file_name=f"{key}.pdf",
        file_sha256="0" * 64,
        page_count=3,
        para_count=3,
        sent_count=3,
        unit_mode="para+sent",
        ingested_at="2026-10-26T00:00:00Z",
    )


def _claim(citations=("alpha",), text="Alpha uses dense vectors for retrieval.") -> Claim:
    return Claim(
        claim_id="claim-01",
        line_start=3,
        line_end=3,
        text=text,
        citations=tuple(citations),
    )


def _paragraph(unit_id: str, page: int = 1) -> HybridHit:
    return HybridHit(
        unit_id=unit_id,
        paper_key=unit_id.split(":")[0],
        page=page,
        unit_type="para",
        text=f"paragraph {unit_id}",
        parent_id="",
        rrf_score=0.03,
        fulltext_rank=1,
        vector_rank=1,
        fulltext_score=2.0,
        vector_distance=0.2,
    )


def _sentence(unit_id: str, text: str, vector, parent: str, page: int = 1) -> UnitRow:
    return UnitRow(
        unit_id=unit_id,
        paper_key=unit_id.split(":")[0],
        page=page,
        unit_type="sent",
        parent_id=parent,
        text=text,
        embedding=tuple(vector),
    )


def _refs(*keys: str) -> dict[str, PaperRef]:
    return {
        key: PaperRef(key=key, file=Path(f"{key}.pdf"), title=f"{key} title") for key in keys
    }


def test_audit_selects_best_sentence_and_aggregates_verdicts() -> None:
    store = FakeStore(
        papers={"alpha": _paper("alpha"), "beta": _paper("beta")},
        paragraph_hits={
            "alpha": [_paragraph("alpha:p1:para1")],
            "beta": [_paragraph("beta:p1:para1")],
        },
        children=[
            _sentence(
                "alpha:p1:sent1",
                "Dense vectors retrieve relevant evidence.",
                (1.0, 0.0),
                "alpha:p1:para1",
            ),
            _sentence(
                "alpha:p1:sent2",
                "Unrelated sentence about weather.",
                (0.0, 1.0),
                "alpha:p1:para1",
            ),
            _sentence(
                "beta:p1:sent1",
                "Beta uses a different method.",
                (1.0, 0.0),
                "beta:p1:para1",
            ),
        ],
    )
    verifier = FixedVerifier({"alpha": "partial", "beta": "unsupported"})
    engine = AuditEngine(store, FakeCache(), verifier, "fake-model")
    report = engine.audit(
        [_claim(("alpha", "beta"))], _refs("alpha", "beta"), "draft.md", "bib.json"
    )

    assert len(report.claims) == 1
    claim = report.claims[0]
    assert claim.verdict == "unsupported"
    assert [check.citation for check in claim.checks] == ["alpha", "beta"]
    assert claim.checks[0].evidence is not None
    assert claim.checks[0].evidence.unit_id == "alpha:p1:sent1"
    assert verifier.calls["alpha"][0].unit_id == "alpha:p1:sent1"
    assert verifier.calls["alpha"][1].unit_id == "alpha:p1:sent2"
    assert report.citation_verdicts == {
        "supported": 0,
        "partial": 1,
        "unsupported": 1,
        "unknown": 0,
    }
    assert report.claim_verdicts["unsupported"] == 1
    assert report.error_count == 0


def test_audit_rejects_unknown_citation_key() -> None:
    store = FakeStore({}, {}, [])
    engine = AuditEngine(store, FakeCache(), FixedVerifier({}), "fake-model")
    with pytest.raises(AuditError, match="missing from bibliography"):
        engine.audit([_claim(("ghost",))], _refs("alpha"), "draft.md", "bib.json")


def test_audit_rejects_unregistered_paper() -> None:
    store = FakeStore({}, {}, [])
    engine = AuditEngine(store, FakeCache(), FixedVerifier({}), "fake-model")
    with pytest.raises(AuditError, match="not ingested: alpha"):
        engine.audit([_claim(("alpha",))], _refs("alpha"), "draft.md", "bib.json")


def test_audit_isolates_one_citation_failure() -> None:
    store = FakeStore(
        papers={"alpha": _paper("alpha"), "beta": _paper("beta")},
        paragraph_hits={"alpha": [_paragraph("alpha:p1:para1")]},
        children=[
            _sentence(
                "alpha:p1:sent1",
                "Dense vectors retrieve evidence.",
                (1.0, 0.0),
                "alpha:p1:para1",
            )
        ],
        fail_keys={"beta"},
    )
    verifier = FixedVerifier({"alpha": "partial"})
    report = AuditEngine(store, FakeCache(), verifier, "fake-model").audit(
        [_claim(("alpha", "beta"))], _refs("alpha", "beta"), "draft.md", "bib.json"
    )
    checks = report.claims[0].checks
    assert checks[0].verdict == "partial"
    assert checks[1].verdict == "unknown"
    assert checks[1].error and "search broke" in checks[1].error
    assert report.claims[0].verdict == "unknown"
    assert report.error_count == 1


def test_audit_falls_back_to_paragraph_without_sentences() -> None:
    paragraph = _paragraph("alpha:p1:para1")
    store = FakeStore(
        papers={"alpha": _paper("alpha")},
        paragraph_hits={"alpha": [paragraph]},
        children=[],
        units={
            "alpha:p1:para1": UnitRow(
                unit_id="alpha:p1:para1",
                paper_key="alpha",
                page=1,
                unit_type="para",
                parent_id="",
                text="Dense vectors retrieve evidence.",
                embedding=(1.0, 0.0),
            )
        },
    )
    verifier = FixedVerifier({"alpha": "partial"})
    report = AuditEngine(store, FakeCache(), verifier, "fake-model").audit(
        [_claim(("alpha",))], _refs("alpha"), "draft.md", "bib.json"
    )
    evidence = report.claims[0].checks[0].evidence
    assert evidence is not None
    assert evidence.unit_type == "para"
    assert evidence.unit_id == "alpha:p1:para1"


def test_audit_warns_when_fulltext_leg_is_empty() -> None:
    store = FakeStore(
        papers={"alpha": _paper("alpha")},
        paragraph_hits={"alpha": [_paragraph("alpha:p1:para1")]},
        children=[
            _sentence(
                "alpha:p1:sent1",
                "Dense vectors retrieve evidence.",
                (1.0, 0.0),
                "alpha:p1:para1",
            )
        ],
    )
    report = AuditEngine(store, FakeCache(), FixedVerifier({}), "fake-model").audit(
        [_claim(("alpha",), text="注意力机制用于引用核对。")],
        _refs("alpha"),
        "draft.md",
        "bib.json",
    )
    assert any("全文检索为空" in warning for warning in report.warnings)
    assert store.search_calls[0][1] == ()


def test_audit_emits_progress_events() -> None:
    store = FakeStore(
        papers={"alpha": _paper("alpha")},
        paragraph_hits={"alpha": [_paragraph("alpha:p1:para1")]},
        children=[
            _sentence(
                "alpha:p1:sent1",
                "Dense vectors retrieve evidence.",
                (1.0, 0.0),
                "alpha:p1:para1",
            )
        ],
    )
    events = []
    AuditEngine(store, FakeCache(), FixedVerifier({"alpha": "partial"}), "fake-model").audit(
        [_claim(("alpha",))],
        _refs("alpha"),
        "draft.md",
        "bib.json",
        on_progress=events.append,
    )
    assert [event["stage"] for event in events] == ["preflight", "claim", "claim", "report"]
    assert (events[0]["done"], events[0]["total"]) == (0, 1)
    assert (events[1]["done"], events[1]["claim_id"]) == (0, "claim-01")
    assert (events[2]["done"], events[2]["total"]) == (1, 1)
    assert "partial" in events[2]["message"]
