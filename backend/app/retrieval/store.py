"""Qdrant vector store keyed by ``chunk_id``.

Phase 3 runs Qdrant in embedded (local-file) mode under ``index_dir/qdrant`` so no server is
needed; setting ``LEGALAI_QDRANT_URL`` switches to a Qdrant server with the same code (ADR 0003).
Embedded mode takes a file lock: only one process (API server *or* index builder) at a time.
"""

import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from qdrant_client import QdrantClient, models

from app.ingestion.models import Chunk

COLLECTION = "chunks"
_ID_NAMESPACE = uuid.UUID("6f1c9a52-8a43-4f0e-9a51-3d0c2b7e9d11")  # fixed: ids stay stable


def point_id(chunk_id: str) -> str:
    """Qdrant ids must be UUIDs or ints; derive a deterministic UUID from the chunk id."""
    return str(uuid.uuid5(_ID_NAMESPACE, chunk_id))


@dataclass(frozen=True)
class VectorHit:
    chunk_id: str
    score: float  # cosine similarity in [-1, 1]


class VectorStore:
    def __init__(self, client: QdrantClient, collection: str = COLLECTION) -> None:
        self._client = client
        self._collection = collection
        self._lock = threading.Lock()  # the embedded client is not safe for concurrent use

    def exists(self) -> bool:
        with self._lock:
            return self._client.collection_exists(self._collection)

    def count(self) -> int:
        with self._lock:
            return self._client.count(self._collection, exact=True).count

    def recreate(self, dimension: int) -> None:
        with self._lock:
            if self._client.collection_exists(self._collection):
                self._client.delete_collection(self._collection)
            self._client.create_collection(
                self._collection,
                vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
            )

    def upsert(self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        points = [
            models.PointStruct(
                id=point_id(chunk.chunk_id),
                vector=list(vector),
                # The corpus JSONL is the source of truth for text; the payload carries only
                # the key plus fields later phases filter on (applicability, doc type).
                payload={"chunk_id": chunk.chunk_id, "doc_id": chunk.doc_id, "kind": chunk.kind},
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        with self._lock:
            self._client.upsert(self._collection, points=points, wait=True)

    def search(self, vector: Sequence[float], limit: int) -> list[VectorHit]:
        with self._lock:
            response = self._client.query_points(
                self._collection, query=list(vector), limit=limit, with_payload=["chunk_id"]
            )
        return [
            VectorHit(chunk_id=str(p.payload["chunk_id"]), score=float(p.score))
            for p in response.points
            if p.payload is not None
        ]

    def close(self) -> None:
        with self._lock:
            self._client.close()
