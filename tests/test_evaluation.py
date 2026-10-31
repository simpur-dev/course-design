import json
from pathlib import Path

import pytest

from yinju.audit import AuditEngine
from yinju.bibliography import PaperRef
from yinju.embeddings import EmbedResult
from yinju.evaluation import (
    ItemResult,
    LabeledItem,
    LabeledSet,
    LabelError,
    compute_metrics,
    evaluate,
    evaluation_to_dict,
    evaluation_to_markdown,
    load_labeled_set,
    write_evaluation,
)
from yinju.store import HybridHit, PaperRecord, UnitRow
from yinju.verdicts import Verdict


class FakeCache:
    def embed(self, texts, batch_size=64, on_progress=None):
        return EmbedResult(
            vectors=tuple((1.0, 0.0) for _ in texts),
            embedded=len(texts),
            computed=len(texts),
            cached=0,
            batches=1,
        )


class FakeStore:
    def __init__(self) -> None:
        self.papers = {"alpha": _paper("alpha"), "beta": _paper("beta")}
        self.pages = {"alpha": 1, "beta": 2}

    def get_paper(self, paper_key):
        return self.papers.get(paper_key)

    def hybrid_search(self, query_embedding, keywords, paper_key, **kwargs):
        return [_paragraph(paper_key, self.pages[paper_key])]

    def fetch_children(self, paper_key, parent_ids, unit_type="sent", limit=1000):
        return [_sentence(paper_key, self.pages[paper_key])]

    def fetch_units(self, unit_ids):
        return []


class FixedVerifier:
    name = "test/fixed"

    def __init__(self, verdicts):
        self.verdicts = verdicts

    def verify(self, claim, paper_key, paper_title, candidates):
        verdict = self.verdicts[claim]
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


def _paragraph(key: str, page: int) -> HybridHit:
    return HybridHit(
        unit_id=f"{key}:p{page}:para1",
        paper_key=key,
        page=page,
        unit_type="para",
        text=f"{key} paragraph",
        parent_id="",
        rrf_score=0.03,
        fulltext_rank=1,
        vector_rank=1,
        fulltext_score=2.0,
        vector_distance=0.2,
    )


def _sentence(key: str, page: int) -> UnitRow:
    return UnitRow(
        unit_id=f"{key}:p{page}:sent1",
        paper_key=key,
        page=page,
        unit_type="sent",
        text=f"{key} sentence",
        parent_id=f"{key}:p{page}:para1",
        embedding=(1.0, 0.0),
    )


def _item(
    item_id: str,
    expected: str,
    predicted: str,
    *,
    expected_pages=(),
    evidence_page=None,
    error=None,
) -> ItemResult:
    return ItemResult(
        item_id=item_id,
        claim=f"claim {item_id}",
        citation="alpha",
        expected=expected,
        predicted=predicted,
        confidence="medium",
        review_required=predicted in {"partial", "unknown"},
        expected_pages=tuple(expected_pages),
        evidence_page=evidence_page,
        evidence_unit_id=f"alpha:p{evidence_page}:sent1" if evidence_page else None,
        evidence_hit=(
            None if not expected_pages else evidence_page in expected_pages
        ),
        reason=f"{expected}->{predicted}",
        seconds=0.5,
        error=error,
    )


def test_load_labeled_set_reads_items(tmp_path: Path) -> None:
    path = tmp_path / "labels.json"
    path.write_text(
        json.dumps(
            {
                "name": "tiny",
                "description": "two items",
                "items": [
                    {
                        "id": "a",
                        "claim": "Alpha uses dense vectors.",
                        "citation": "alpha",
                        "label": "supported",
                        "evidence_pages": [1, 2],
                        "evidence_units": ["alpha:p1:sent1"],
                    },
                    {
                        "id": "b",
                        "claim": "Alpha uses sparse vectors.",
                        "citation": "alpha",
                        "label": "unsupported",
                        "evidence_pages": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    label_set = load_labeled_set(path)

    assert label_set.name == "tiny"
    assert [item.item_id for item in label_set.items] == ["a", "b"]
    assert label_set.items[0].evidence_pages == (1, 2)
    assert label_set.items[1].evidence_pages == ()


def test_shipped_labels_are_valid() -> None:
    path = Path(__file__).resolve().parents[1] / "data" / "samples" / "labels.json"

    label_set = load_labeled_set(path)

    assert label_set.name == "samples-v1"
    assert len(label_set.items) == 16
    assert sum(item.label == "unsupported" for item in label_set.items) == 7
    assert all(item.citation in {"vaswani2017", "devlin2019"} for item in label_set.items)


@pytest.mark.parametrize(
    "items, message",
    [
        ([], "non-empty"),
        ([{"id": "a", "claim": "x", "citation": "alpha", "label": "maybe"}], "label must be"),
        (
            [
                {"id": "a", "claim": "x", "citation": "alpha", "label": "supported"},
                {"id": "a", "claim": "y", "citation": "alpha", "label": "supported"},
            ],
            "duplicate item id",
        ),
        (
            [
                {
                    "id": "a",
                    "claim": "x",
                    "citation": "alpha",
                    "label": "supported",
                    "evidence_pages": [0],
                }
            ],
            "positive integers",
        ),
        (
            [
                {
                    "id": "a",
                    "claim": "x",
                    "citation": "alpha",
                    "label": "supported",
                    "evidence_units": ["alpha:p1:sent1"],
                }
            ],
            "require evidence_pages",
        ),
    ],
)
def test_load_labeled_set_rejects_invalid_items(
    tmp_path: Path, items, message: str
) -> None:
    path = tmp_path / "labels.json"
    path.write_text(
        json.dumps({"name": "tiny", "items": items}),
        encoding="utf-8",
    )

    with pytest.raises(LabelError, match=message):
        load_labeled_set(path)


def test_evaluate_maps_verdicts_and_evidence_pages() -> None:
    items = (
        LabeledItem(
            item_id="a1",
            claim="Alpha uses dense vectors.",
            citation="alpha",
            label="supported",
            evidence_pages=(1,),
            evidence_units=(),
            source="test",
            notes="",
        ),
        LabeledItem(
            item_id="a2",
            claim="Alpha uses sparse vectors.",
            citation="alpha",
            label="unsupported",
            evidence_pages=(2,),
            evidence_units=(),
            source="test",
            notes="",
        ),
        LabeledItem(
            item_id="a3",
            claim="Beta uses graphs.",
            citation="beta",
            label="supported",
            evidence_pages=(),
            evidence_units=(),
            source="test",
            notes="",
        ),
    )
    label_set = LabeledSet(name="unit", description="", items=items)
    store = FakeStore()
    verifier = FixedVerifier(
        {
            "Alpha uses dense vectors.": "partial",
            "Alpha uses sparse vectors.": "unsupported",
            "Beta uses graphs.": "unsupported",
        }
    )
    engine = AuditEngine(
        store,
        FakeCache(),
        verifier,
        embedding_model="fake",
        paragraph_limit=5,
    )
    refs = {
        "alpha": PaperRef(key="alpha", file=Path("alpha.pdf")),
        "beta": PaperRef(key="beta", file=Path("beta.pdf")),
    }

    report = evaluate(engine, label_set, refs, "bib.json")

    assert [(item.expected, item.predicted) for item in report.items] == [
        ("supported", "partial"),
        ("unsupported", "unsupported"),
        ("supported", "unsupported"),
    ]
    assert [item.evidence_hit for item in report.items] == [True, False, None]
    metrics = report.metrics
    assert metrics["total"] == 3
    assert metrics["labels"] == {
        "supported": 2,
        "partial": 0,
        "unsupported": 1,
        "unknown": 0,
    }
    assert metrics["predictions"] == {
        "supported": 0,
        "partial": 1,
        "unsupported": 2,
        "unknown": 0,
    }
    assert metrics["strict_accuracy"] == pytest.approx(1 / 3, abs=1e-4)
    assert metrics["unsupported_recall"] == 1.0
    assert metrics["unsupported_precision"] == 0.5
    assert metrics["unsupported_missed"] == 0
    assert metrics["unsupported_auto_pass"] == 0
    assert metrics["unsupported_handled_rate"] == 1.0
    assert metrics["review_rate"] == pytest.approx(1 / 3, abs=1e-4)
    assert metrics["supported_review_rate"] == 0.5
    assert metrics["supported_auto_rate"] == 0.0
    assert metrics["evidence_page_labeled"] == 2
    assert metrics["evidence_page_hit_rate"] == 0.5
    assert metrics["errors"] == 0


def test_evaluate_rejects_unknown_citation() -> None:
    label_set = LabeledSet(
        name="unit",
        description="",
        items=(
            LabeledItem(
                item_id="a1",
                claim="Alpha uses dense vectors.",
                citation="gamma",
                label="supported",
                evidence_pages=(),
                evidence_units=(),
                source="test",
                notes="",
            ),
        ),
    )

    with pytest.raises(LabelError, match="missing from bibliography"):
        evaluate(AuditEngine(FakeStore(), FakeCache(), FixedVerifier({}), "fake"), label_set, {}, "bib.json")


def test_compute_metrics_handles_empty_and_misses() -> None:
    empty = compute_metrics([])
    assert empty["total"] == 0
    assert empty["unsupported_recall"] is None
    assert empty["strict_accuracy"] is None

    items = [
        _item("a", "unsupported", "partial", expected_pages=(3,), evidence_page=1),
        _item("b", "unsupported", "unsupported", expected_pages=(), error="boom"),
    ]
    metrics = compute_metrics(items)
    assert metrics["unsupported_recall"] == 0.5
    assert metrics["unsupported_precision"] == 1.0
    assert metrics["unsupported_missed"] == 1
    assert metrics["unsupported_auto_pass"] == 0
    assert metrics["unsupported_handled_rate"] == 1.0
    assert metrics["evidence_page_hit_rate"] == 0.0
    assert metrics["errors"] == 1


def test_compute_metrics_counts_silent_auto_pass() -> None:
    metrics = compute_metrics(
        [
            _item("a", "unsupported", "supported"),
            _item("b", "unsupported", "partial"),
        ]
    )

    assert metrics["unsupported_recall"] == 0.0
    assert metrics["unsupported_auto_pass"] == 1
    assert metrics["unsupported_handled_rate"] == 0.5


def test_evaluation_writers_include_metrics(tmp_path: Path) -> None:
    label_set = LabeledSet(
        name="unit set",
        description="desc",
        items=(
            LabeledItem(
                item_id="a1",
                claim="Alpha uses dense vectors.",
                citation="alpha",
                label="supported",
                evidence_pages=(1,),
                evidence_units=(),
                source="test",
                notes="",
            ),
        ),
    )
    engine = AuditEngine(
        FakeStore(),
        FakeCache(),
        FixedVerifier({"Alpha uses dense vectors.": "partial"}),
        embedding_model="fake",
    )
    report = evaluate(
        engine,
        label_set,
        {"alpha": PaperRef(key="alpha", file=Path("alpha.pdf"))},
        "bib.json",
    )

    files = write_evaluation(report, tmp_path)

    payload = json.loads(files["json"].read_text(encoding="utf-8"))
    assert payload["dataset"] == "unit set"
    assert payload["metrics"]["unsupported_recall"] is None
    assert payload["items"][0]["expected_pages"] == [1]
    markdown = files["markdown"].read_text(encoding="utf-8")
    assert "# 引用核对评测报告" in markdown
    assert "混淆矩阵" in markdown
    assert "不支持召回率" in markdown


def test_evaluation_to_dict_and_markdown_baseline_caveat() -> None:
    label_set = LabeledSet(
        name="unit",
        description="",
        items=(
            LabeledItem(
                item_id="a1",
                claim="Alpha uses dense vectors.",
                citation="alpha",
                label="supported",
                evidence_pages=(1,),
                evidence_units=(),
                source="test",
                notes="",
            ),
        ),
    )
    engine = AuditEngine(
        FakeStore(),
        FakeCache(),
        FixedVerifier({"Alpha uses dense vectors.": "partial"}),
        embedding_model="fake",
    )
    report = evaluate(
        engine,
        label_set,
        {"alpha": PaperRef(key="alpha", file=Path("alpha.pdf"))},
        "bib.json",
    )
    payload = evaluation_to_dict(report)
    assert payload["baseline_cannot_emit_supported"] is False
    markdown = evaluation_to_markdown(report)
    assert "verifier=none" not in markdown
