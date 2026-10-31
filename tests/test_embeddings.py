import pytest

from yinju.embeddings import EmbeddingCache, EmbeddingError, embedding_dimension, embedding_model_id


class FakeEmbedder:
    dimension = 3
    model_name = "fake-3d"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def name(self) -> str:
        return "fake"

    def __call__(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [
            [float(len(text)), float(sum(ord(char) for char in text) % 97), 0.25]
            for text in texts
        ]


def test_embedding_identity_helpers() -> None:
    embedder = FakeEmbedder()
    assert embedding_model_id(embedder) == "fake|fake-3d"
    assert embedding_dimension(embedder) == 3


def test_cache_embeds_unique_misses_then_reuses(tmp_path) -> None:
    embedder = FakeEmbedder()
    cache = EmbeddingCache(tmp_path / "cache.sqlite3", embedder)

    first = cache.embed(["a", "bb", "a"])
    assert (first.embedded, first.computed, first.cached, first.batches) == (3, 2, 0, 1)
    assert embedder.calls == [["a", "bb"]]
    assert first.vectors[0] == first.vectors[2]

    second = cache.embed(["a", "bb", "ccc"])
    assert (second.embedded, second.computed, second.cached, second.batches) == (1, 1, 2, 1)
    assert embedder.calls[-1] == ["ccc"]


def test_cache_survives_new_instance(tmp_path) -> None:
    path = tmp_path / "cache.sqlite3"
    embedder = FakeEmbedder()
    EmbeddingCache(path, embedder).embed(["alpha", "beta"])
    calls = len(embedder.calls)

    reopened = EmbeddingCache(path, embedder)
    result = reopened.embed(["alpha", "beta"])
    assert (result.embedded, result.cached) == (0, 2)
    assert len(embedder.calls) == calls


def test_cache_isolates_models(tmp_path) -> None:
    path = tmp_path / "cache.sqlite3"
    embedder = FakeEmbedder()
    EmbeddingCache(path, embedder).embed(["alpha"])
    other = EmbeddingCache(path, embedder, model_id="other-model")
    result = other.embed(["alpha"])
    assert (result.embedded, result.cached) == (1, 0)
    assert len(embedder.calls) == 2


def test_cache_reports_batch_progress(tmp_path) -> None:
    embedder = FakeEmbedder()
    cache = EmbeddingCache(tmp_path / "cache.sqlite3", embedder)
    progress: list[tuple[int, int]] = []
    result = cache.embed(
        ["one", "two", "three"], batch_size=1, on_progress=lambda done, total: progress.append((done, total))
    )
    assert result.batches == 3
    assert progress == [(1, 3), (2, 3), (3, 3)]


def test_cache_rejects_wrong_dimension(tmp_path) -> None:
    class BadEmbedder:
        dimension = 3
        model_name = "bad"

        def name(self) -> str:
            return "bad"

        def __call__(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 2.0] for _ in texts]

    cache = EmbeddingCache(tmp_path / "cache.sqlite3", BadEmbedder())
    with pytest.raises(EmbeddingError, match="dimension 2"):
        cache.embed(["alpha"])


def test_cache_handles_empty_input(tmp_path) -> None:
    embedder = FakeEmbedder()
    cache = EmbeddingCache(tmp_path / "cache.sqlite3", embedder)
    result = cache.embed([])
    assert result.vectors == ()
    assert result.embedded == result.computed == result.cached == result.batches == 0
    assert embedder.calls == []


def test_cache_rejects_non_positive_batch_size(tmp_path) -> None:
    cache = EmbeddingCache(tmp_path / "cache.sqlite3", FakeEmbedder())
    with pytest.raises(ValueError, match="batch_size"):
        cache.embed(["alpha"], batch_size=0)
