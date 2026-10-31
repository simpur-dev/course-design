from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pymysql
import pyseekdb

from ..core.config import Settings
from .units import EvidenceUnit

COLLECTION_NAME = "evidence_units"
UNIT_MODE = "para+sent"
RRF_RANK_CONSTANT = 60

_PAPER_COLUMNS = (
    "paper_key",
    "title",
    "authors",
    "year",
    "source_url",
    "file_name",
    "file_sha256",
    "page_count",
    "para_count",
    "sent_count",
    "unit_mode",
    "ingested_at",
)

_PAPER_DDL = """
CREATE TABLE IF NOT EXISTS paper (
    paper_key VARCHAR(128) NOT NULL,
    title VARCHAR(512) NOT NULL,
    authors VARCHAR(512) NOT NULL,
    year SMALLINT NULL,
    source_url VARCHAR(1024) NOT NULL,
    file_name VARCHAR(512) NOT NULL,
    file_sha256 CHAR(64) NOT NULL,
    page_count INT NOT NULL,
    para_count INT NOT NULL,
    sent_count INT NOT NULL,
    unit_mode VARCHAR(16) NOT NULL,
    ingested_at VARCHAR(32) NOT NULL,
    PRIMARY KEY (paper_key)
) DEFAULT CHARSET = utf8mb4
"""


@dataclass(frozen=True)
class PaperRecord:
    paper_key: str
    title: str
    authors: str
    year: int | None
    source_url: str
    file_name: str
    file_sha256: str
    page_count: int
    para_count: int
    sent_count: int
    unit_mode: str
    ingested_at: str


@dataclass(frozen=True)
class SearchHit:
    unit_id: str
    paper_key: str
    page: int
    unit_type: str
    text: str
    distance: float
    parent_id: str


@dataclass(frozen=True)
class HybridHit:
    unit_id: str
    paper_key: str
    page: int
    unit_type: str
    text: str
    parent_id: str
    rrf_score: float
    fulltext_rank: int | None
    vector_rank: int | None
    fulltext_score: float | None
    vector_distance: float | None


@dataclass(frozen=True)
class UnitRow:
    unit_id: str
    paper_key: str
    page: int
    unit_type: str
    parent_id: str
    text: str
    embedding: tuple[float, ...] | None


class EvidenceStore:
    def __init__(
        self,
        settings: Settings,
        embedder: Any,
        collection_name: str = COLLECTION_NAME,
    ) -> None:
        self.settings = settings
        self.embedder = embedder
        self.collection_name = collection_name
        self._collection: Any = None

    @property
    def collection(self) -> Any:
        if self._collection is None:
            self.ensure()
        return self._collection

    def ensure(self) -> EvidenceStore:
        admin = pyseekdb.AdminClient(
            host=self.settings.seekdb_host,
            port=self.settings.seekdb_port,
            user=self.settings.seekdb_user,
            password=self.settings.seekdb_password.get_secret_value(),
        )
        databases = {database.name for database in admin.list_databases()}
        if self.settings.seekdb_database not in databases:
            admin.create_database(self.settings.seekdb_database)

        connection = self._sql()
        try:
            with connection.cursor() as cursor:
                cursor.execute(_PAPER_DDL)
            connection.commit()
        finally:
            connection.close()

        client = pyseekdb.Client(
            host=self.settings.seekdb_host,
            port=self.settings.seekdb_port,
            user=self.settings.seekdb_user,
            password=self.settings.seekdb_password.get_secret_value(),
            database=self.settings.seekdb_database,
        )
        self._collection = client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self.embedder,
        )
        return self

    def get_paper(self, paper_key: str) -> PaperRecord | None:
        connection = self._sql()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {', '.join(_PAPER_COLUMNS)} FROM paper WHERE paper_key = %s",
                    (paper_key,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        return _paper_from_row(row) if row else None

    def list_papers(self) -> list[PaperRecord]:
        connection = self._sql()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {', '.join(_PAPER_COLUMNS)} FROM paper ORDER BY paper_key"
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        return [_paper_from_row(row) for row in rows]

    def upsert_paper(self, record: PaperRecord) -> None:
        placeholders = ", ".join("%s" for _ in _PAPER_COLUMNS)
        values = tuple(getattr(record, column) for column in _PAPER_COLUMNS)
        connection = self._sql()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"REPLACE INTO paper ({', '.join(_PAPER_COLUMNS)}) VALUES ({placeholders})",
                    values,
                )
            connection.commit()
        finally:
            connection.close()

    def replace_units(
        self,
        paper_key: str,
        units: tuple[EvidenceUnit, ...] | list[EvidenceUnit],
        vectors: tuple[tuple[float, ...], ...] | list[tuple[float, ...]],
        batch_size: int = 128,
    ) -> None:
        if len(units) != len(vectors):
            raise ValueError(f"{len(units)} units but {len(vectors)} vectors")
        collection = self.collection
        collection.delete(where={"paper_key": {"$eq": paper_key}})
        for start in range(0, len(units), batch_size):
            batch_units = units[start : start + batch_size]
            batch_vectors = vectors[start : start + batch_size]
            collection.upsert(
                ids=[unit.unit_id for unit in batch_units],
                documents=[unit.text for unit in batch_units],
                metadatas=[unit.to_metadata() for unit in batch_units],
                embeddings=[list(vector) for vector in batch_vectors],
            )

    def search(
        self,
        query: str,
        paper_key: str,
        unit_type: str = "sent",
        limit: int = 5,
    ) -> list[SearchHit]:
        if unit_type not in {"para", "sent"}:
            raise ValueError("unit_type must be 'para' or 'sent'")
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        where = {
            "paper_key": {"$eq": paper_key},
            "unit_type": {"$eq": unit_type},
        }
        result = self.collection.query(
            query_texts=[query],
            n_results=limit,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        hits: list[SearchHit] = []
        for unit_id, text, metadata, distance in zip(ids, documents, metadatas, distances):
            hits.append(
                SearchHit(
                    unit_id=unit_id,
                    paper_key=str(metadata.get("paper_key", paper_key)),
                    page=int(metadata.get("page", 0)),
                    unit_type=str(metadata.get("unit_type", unit_type)),
                    text=text or "",
                    distance=float(distance),
                    parent_id=str(metadata.get("parent_id", "")),
                )
            )
        return hits

    def hybrid_search(
        self,
        query_embedding: Sequence[float],
        keywords: Sequence[str],
        paper_key: str,
        unit_type: str = "para",
        limit: int = 5,
        per_leg: int = 20,
        rrf_k: int = RRF_RANK_CONSTANT,
    ) -> list[HybridHit]:
        """Search one paper with a full-text leg, a vector leg, and local RRF."""
        if unit_type not in {"para", "sent"}:
            raise ValueError("unit_type must be 'para' or 'sent'")
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        if not 1 <= per_leg <= 200:
            raise ValueError("per_leg must be between 1 and 200")
        if rrf_k < 1:
            raise ValueError("rrf_k must be positive")
        if not query_embedding:
            raise ValueError("query_embedding must not be empty")

        where = {
            "paper_key": {"$eq": paper_key},
            "unit_type": {"$eq": unit_type},
        }
        terms = [term for term in dict.fromkeys(keywords) if term]
        fulltext = []
        if terms:
            where_document = (
                {"$contains": terms[0]}
                if len(terms) == 1
                else {"$or": [{"$contains": term} for term in terms]}
            )
            result = self.collection.hybrid_search(
                query={
                    "where_document": where_document,
                    "where": where,
                    "n_results": per_leg,
                },
                n_results=per_leg,
                include=["documents", "metadatas", "distances"],
            )
            fulltext = _packets(result)

        vector_result = self.collection.query(
            query_embeddings=[list(query_embedding)],
            n_results=per_leg,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        vector = _packets(vector_result)

        merged: dict[str, dict[str, Any]] = {}
        for rank, packet in enumerate(fulltext, start=1):
            item = merged.setdefault(packet["unit_id"], dict(packet))
            item["fulltext_rank"] = rank
            item["fulltext_score"] = packet["distance"]
        for rank, packet in enumerate(vector, start=1):
            item = merged.setdefault(packet["unit_id"], dict(packet))
            item["vector_rank"] = rank
            item["vector_distance"] = packet["distance"]

        for item in merged.values():
            rrf = 0.0
            if item.get("fulltext_rank") is not None:
                rrf += 1.0 / (rrf_k + item["fulltext_rank"])
            if item.get("vector_rank") is not None:
                rrf += 1.0 / (rrf_k + item["vector_rank"])
            item["rrf_score"] = rrf

        ordered = sorted(merged.values(), key=lambda item: (-item["rrf_score"], item["unit_id"]))
        return [
            HybridHit(
                unit_id=item["unit_id"],
                paper_key=item["paper_key"],
                page=item["page"],
                unit_type=item["unit_type"],
                text=item["text"],
                parent_id=item["parent_id"],
                rrf_score=item["rrf_score"],
                fulltext_rank=item.get("fulltext_rank"),
                vector_rank=item.get("vector_rank"),
                fulltext_score=item.get("fulltext_score"),
                vector_distance=item.get("vector_distance"),
            )
            for item in ordered[:limit]
        ]

    def fetch_units(self, unit_ids: Sequence[str]) -> list[UnitRow]:
        ids = [str(unit_id) for unit_id in dict.fromkeys(unit_ids) if str(unit_id)]
        if not ids:
            return []
        result = self.collection.get(
            ids=ids,
            include=["documents", "metadatas", "embeddings"],
        )
        return _rows(result)

    def fetch_children(
        self,
        paper_key: str,
        parent_ids: Sequence[str],
        unit_type: str = "sent",
        limit: int = 1000,
    ) -> list[UnitRow]:
        parents = [str(parent_id) for parent_id in dict.fromkeys(parent_ids) if str(parent_id)]
        if not parents:
            return []
        if len(parents) > 50:
            raise ValueError("at most 50 parent ids can be fetched at once")
        result = self.collection.get(
            where={
                "paper_key": {"$eq": paper_key},
                "unit_type": {"$eq": unit_type},
                "parent_id": {"$in": parents},
            },
            limit=limit,
            include=["documents", "metadatas", "embeddings"],
        )
        return _rows(result)

    def _sql(self) -> pymysql.connections.Connection:
        return pymysql.connect(
            host=self.settings.seekdb_host,
            port=self.settings.seekdb_port,
            user=self.settings.seekdb_user,
            password=self.settings.seekdb_password.get_secret_value(),
            database=self.settings.seekdb_database,
            charset="utf8mb4",
            connect_timeout=5,
            read_timeout=30,
            write_timeout=30,
            autocommit=False,
        )


def _paper_from_row(row: tuple) -> PaperRecord:
    return PaperRecord(**dict(zip(_PAPER_COLUMNS, row, strict=True)))


def _packets(result: dict[str, Any]) -> list[dict[str, Any]]:
    ids = (result.get("ids") or [[]])[0] or []
    documents = (result.get("documents") or [[]])[0] or []
    metadatas = (result.get("metadatas") or [[]])[0] or []
    distances = (result.get("distances") or [[]])[0] or []
    packets: list[dict[str, Any]] = []
    for index, unit_id in enumerate(ids):
        metadata = metadatas[index] if index < len(metadatas) else {}
        metadata = metadata or {}
        distance = distances[index] if index < len(distances) else None
        packets.append(
            {
                "unit_id": str(unit_id),
                "paper_key": str(metadata.get("paper_key", "")),
                "page": int(metadata.get("page", 0)),
                "unit_type": str(metadata.get("unit_type", "")),
                "parent_id": str(metadata.get("parent_id", "")),
                "text": documents[index] if index < len(documents) else "",
                "distance": float(distance) if distance is not None else 0.0,
            }
        )
    return packets


def _rows(result: dict[str, Any]) -> list[UnitRow]:
    ids = result.get("ids") or []
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []
    embeddings = result.get("embeddings") or []
    rows: list[UnitRow] = []
    for index, unit_id in enumerate(ids):
        metadata = metadatas[index] if index < len(metadatas) else {}
        metadata = metadata or {}
        embedding = embeddings[index] if index < len(embeddings) else None
        rows.append(
            UnitRow(
                unit_id=str(unit_id),
                paper_key=str(metadata.get("paper_key", "")),
                page=int(metadata.get("page", 0)),
                unit_type=str(metadata.get("unit_type", "")),
                parent_id=str(metadata.get("parent_id", "")),
                text=documents[index] if index < len(documents) else "",
                embedding=tuple(float(value) for value in embedding) if embedding else None,
            )
        )
    return rows
