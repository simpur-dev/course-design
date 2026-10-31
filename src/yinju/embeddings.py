from __future__ import annotations

import array
import hashlib
import sqlite3
from collections.abc import Callable, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

Embedder = Callable[[list[str]], Sequence[Sequence[float]]]
ProgressCallback = Callable[[int, int], None]


class EmbeddingError(RuntimeError):
    pass


@dataclass(frozen=True)
class EmbedResult:
    vectors: tuple[tuple[float, ...], ...]
    embedded: int
    computed: int
    cached: int
    batches: int


def embedding_model_id(embedder: object) -> str:
    name = getattr(embedder, "name", None)
    name = name() if callable(name) else name
    model = getattr(embedder, "model_name", None)
    model = model() if callable(model) else model
    parts = [str(part) for part in (name, model) if part]
    return "|".join(parts) or type(embedder).__name__


def embedding_dimension(embedder: object) -> int | None:
    dimension = getattr(embedder, "dimension", None)
    dimension = dimension() if callable(dimension) else dimension
    return dimension if isinstance(dimension, int) else None


class EmbeddingCache:
    def __init__(
        self,
        path: Path,
        embedder: Embedder,
        model_id: str | None = None,
    ) -> None:
        self.path = Path(path)
        self.embedder = embedder
        self.model_id = model_id or embedding_model_id(embedder)
        self.dimension = embedding_dimension(embedder)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def embed(
        self,
        texts: Sequence[str],
        batch_size: int = 64,
        on_progress: ProgressCallback | None = None,
    ) -> EmbedResult:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        items = list(texts)
        if not items:
            return EmbedResult(vectors=(), embedded=0, computed=0, cached=0, batches=0)

        hashes = [hashlib.sha256(text.encode("utf-8")).hexdigest() for text in items]
        known = self._load(hashes)

        missing: dict[str, str] = {}
        for text, text_hash in zip(items, hashes):
            if text_hash not in known and text_hash not in missing:
                missing[text_hash] = text

        embedded = sum(1 for text_hash in hashes if text_hash not in known)
        batches = 0
        pending = list(missing.items())
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            batch_texts = [text for _, text in batch]
            raw_vectors = self.embedder(batch_texts)
            vectors = self._validate(raw_vectors, len(batch))
            self._store([(text_hash, vector) for (text_hash, _), vector in zip(batch, vectors)])
            for (text_hash, _), vector in zip(batch, vectors):
                known[text_hash] = vector
            batches += 1
            if on_progress is not None:
                done = min(start + len(batch), len(pending))
                on_progress(done, len(pending))

        return EmbedResult(
            vectors=tuple(known[text_hash] for text_hash in hashes),
            embedded=embedded,
            computed=len(missing),
            cached=len(items) - embedded,
            batches=batches,
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _init_db(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS embedding ("
                "model TEXT NOT NULL, "
                "text_sha256 TEXT NOT NULL, "
                "dim INTEGER NOT NULL, "
                "vector BLOB NOT NULL, "
                "PRIMARY KEY (model, text_sha256))"
            )

    def _load(self, hashes: list[str]) -> dict[str, tuple[float, ...]]:
        known: dict[str, tuple[float, ...]] = {}
        with closing(self._connect()) as connection:
            for start in range(0, len(hashes), 400):
                chunk = hashes[start : start + 400]
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    "SELECT text_sha256, dim, vector FROM embedding "
                    f"WHERE model = ? AND text_sha256 IN ({placeholders})",
                    [self.model_id, *chunk],
                ).fetchall()
                for text_hash, dimension, blob in rows:
                    known[text_hash] = _decode(blob, dimension)
        return known

    def _store(self, rows: list[tuple[str, tuple[float, ...]]]) -> None:
        payload = [
            (self.model_id, text_hash, len(vector), _encode(vector))
            for text_hash, vector in rows
        ]
        with closing(self._connect()) as connection, connection:
            connection.executemany(
                "INSERT OR REPLACE INTO embedding (model, text_sha256, dim, vector) "
                "VALUES (?, ?, ?, ?)",
                payload,
            )

    def _validate(
        self, raw_vectors: Sequence[Sequence[float]], expected: int
    ) -> list[tuple[float, ...]]:
        vectors = [tuple(float(value) for value in vector) for vector in raw_vectors]
        if len(vectors) != expected:
            raise EmbeddingError(f"embedder returned {len(vectors)} vectors for {expected} texts")
        if not vectors:
            return vectors
        if self.dimension is None:
            self.dimension = len(vectors[0])
        for vector in vectors:
            if len(vector) != self.dimension:
                raise EmbeddingError(
                    f"embedder returned dimension {len(vector)}, expected {self.dimension}"
                )
        return vectors


def _encode(vector: tuple[float, ...]) -> bytes:
    return array.array("f", vector).tobytes()


def _decode(blob: bytes, dimension: int) -> tuple[float, ...]:
    values = array.array("f")
    values.frombytes(blob)
    if len(values) != dimension:
        raise EmbeddingError(f"cached vector has {len(values)} values, expected {dimension}")
    return tuple(values)
