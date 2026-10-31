import pytest

from backend.core.config import Settings
from backend.evidence.store import EvidenceStore


def _result(ids, distances):
    return {
        "ids": [ids],
        "documents": [[f"text for {unit_id}" for unit_id in ids]],
        "metadatas": [
            [
                {
                    "paper_key": "alpha",
                    "page": 1,
                    "unit_type": "para",
                    "parent_id": "",
                }
                for _ in ids
            ]
        ],
        "distances": [distances],
    }


class FakeCollection:
    def __init__(self) -> None:
        self.ft_result = _result(["alpha:p1:para1", "alpha:p2:para1"], [2.0, 1.0])
        self.vector_result = _result(["alpha:p2:para1", "alpha:p3:para1"], [0.2, 0.4])
        self.ft_calls = []
        self.vector_calls = []
        self.get_calls = []

    def hybrid_search(self, **kwargs):
        self.ft_calls.append(kwargs)
        return self.ft_result

    def query(self, **kwargs):
        self.vector_calls.append(kwargs)
        return self.vector_result

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        ids = ["alpha:p1:sent1", "alpha:p1:sent2"]
        return {
            "ids": ids,
            "documents": ["first sentence", "second sentence"],
            "metadatas": [
                {
                    "paper_key": "alpha",
                    "page": 1,
                    "unit_type": "sent",
                    "parent_id": "alpha:p1:para1",
                },
                {
                    "paper_key": "alpha",
                    "page": 1,
                    "unit_type": "sent",
                    "parent_id": "alpha:p1:para1",
                },
            ],
            "embeddings": [[1.0, 0.0], [0.0, 1.0]],
        }


def _store() -> tuple[EvidenceStore, FakeCollection]:
    store = EvidenceStore(Settings(_env_file=None), embedder=object())
    collection = FakeCollection()
    store._collection = collection
    return store, collection


def test_hybrid_search_fuses_fulltext_and_vector_with_rrf() -> None:
    store, collection = _store()
    hits = store.hybrid_search(
        [1.0, 0.0],
        ["dense", "retrieval"],
        "alpha",
        unit_type="para",
        limit=5,
        per_leg=20,
    )
    assert [hit.unit_id for hit in hits] == [
        "alpha:p2:para1",
        "alpha:p1:para1",
        "alpha:p3:para1",
    ]
    both = hits[0]
    assert (both.fulltext_rank, both.vector_rank) == (2, 1)
    assert both.fulltext_score == 1.0
    assert both.vector_distance == 0.2
    assert both.rrf_score == pytest.approx(1 / 62 + 1 / 61)
    assert (hits[1].fulltext_rank, hits[1].vector_rank) == (1, None)
    assert (hits[2].fulltext_rank, hits[2].vector_rank) == (None, 2)

    ft_call = collection.ft_calls[0]
    assert ft_call["query"]["where"] == {
        "paper_key": {"$eq": "alpha"},
        "unit_type": {"$eq": "para"},
    }
    assert ft_call["query"]["where_document"] == {
        "$or": [{"$contains": "dense"}, {"$contains": "retrieval"}]
    }
    assert collection.vector_calls[0]["where"] == ft_call["query"]["where"]
    assert collection.vector_calls[0]["query_embeddings"] == [[1.0, 0.0]]


def test_hybrid_search_single_keyword_and_no_keyword_leg() -> None:
    store, collection = _store()
    store.hybrid_search([1.0, 0.0], ["dense"], "alpha")
    assert collection.ft_calls[0]["query"]["where_document"] == {"$contains": "dense"}

    store.hybrid_search([1.0, 0.0], [], "alpha")
    assert len(collection.ft_calls) == 1
    assert collection.vector_calls[-1]["where"]["paper_key"] == {"$eq": "alpha"}


def test_hybrid_search_validates_arguments() -> None:
    store, _ = _store()
    with pytest.raises(ValueError, match="unit_type"):
        store.hybrid_search([1.0], ["x"], "alpha", unit_type="doc")
    with pytest.raises(ValueError, match="limit"):
        store.hybrid_search([1.0], ["x"], "alpha", limit=0)
    with pytest.raises(ValueError, match="per_leg"):
        store.hybrid_search([1.0], ["x"], "alpha", per_leg=0)
    with pytest.raises(ValueError, match="rrf_k"):
        store.hybrid_search([1.0], ["x"], "alpha", rrf_k=0)
    with pytest.raises(ValueError, match="query_embedding"):
        store.hybrid_search([], ["x"], "alpha")


def test_fetch_children_casts_rows_and_filters() -> None:
    store, collection = _store()
    rows = store.fetch_children("alpha", ["alpha:p1:para1"])
    assert [row.unit_id for row in rows] == ["alpha:p1:sent1", "alpha:p1:sent2"]
    assert rows[0].embedding == (1.0, 0.0)
    assert collection.get_calls[0]["where"] == {
        "paper_key": {"$eq": "alpha"},
        "unit_type": {"$eq": "sent"},
        "parent_id": {"$in": ["alpha:p1:para1"]},
    }
    assert store.fetch_children("alpha", []) == []
    with pytest.raises(ValueError, match="at most 50"):
        store.fetch_children("alpha", [f"p{index}" for index in range(51)])


def test_fetch_units_deduplicates_ids() -> None:
    store, collection = _store()
    rows = store.fetch_units(["a", "a", ""])
    assert len(rows) == 2
    assert collection.get_calls[0]["ids"] == ["a"]
    assert store.fetch_units([]) == []
