"""Build the dense index and search it."""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import structlog
from pydantic import BaseModel

from app.ingestion.models import Chunk
from app.providers.embedding import EmbeddingProvider
from app.providers.reranker import RerankerProvider
from app.retrieval.bm25 import BM25Index
from app.retrieval.corpus import Corpus
from app.retrieval.store import VectorStore

logger = structlog.get_logger(__name__)

META_FILE = "index_meta.json"


class IndexNotReadyError(RuntimeError):
    """No usable index: run ``python -m scripts.build_index``."""


class IndexMeta(BaseModel):
    embedding_model: str
    dimension: int
    chunk_count: int
    corpus_fingerprint: str
    built_at: datetime

    @classmethod
    def read(cls, index_dir: Path) -> "IndexMeta | None":
        path = index_dir / META_FILE
        return cls.model_validate_json(path.read_text(encoding="utf-8")) if path.is_file() else None

    def write(self, index_dir: Path) -> None:
        index_dir.mkdir(parents=True, exist_ok=True)
        (index_dir / META_FILE).write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")


def build_index(
    corpus: Corpus,
    embedder: EmbeddingProvider,
    store: VectorStore,
    index_dir: Path,
    batch_size: int = 64,
    on_progress: Callable[[int, int], None] | None = None,
) -> IndexMeta:
    """Embed every retrieval unit (``context`` header + text) and replace the collection."""
    units = corpus.retrieval_units()
    store.recreate(embedder.dimension)
    started = time.perf_counter()
    for start in range(0, len(units), batch_size):
        batch = units[start : start + batch_size]
        store.upsert(batch, embedder.embed_documents([c.embed_text for c in batch]))
        if on_progress is not None:
            on_progress(min(start + batch_size, len(units)), len(units))
    meta = IndexMeta(
        embedding_model=embedder.model_name,
        dimension=embedder.dimension,
        chunk_count=len(units),
        corpus_fingerprint=corpus.fingerprint(),
        built_at=datetime.now(UTC),
    )
    meta.write(index_dir)
    logger.info(
        "index_built",
        chunks=len(units),
        model=embedder.model_name,
        seconds=round(time.perf_counter() - started, 1),
    )
    return meta


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: Chunk
    score: float
    rank: int  # 1-based


RetrievalMode = Literal["dense", "bm25", "hybrid"]
# replace: final order = cross-encoder order. fuse: RRF of first-stage and cross-encoder orders
# (the cross-encoder alone under-ranks short statute clauses; see ADR 0004).
RerankStrategy = Literal["replace", "fuse"]


def rrf_fuse(rankings: Sequence[Sequence[str]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal rank fusion: score(d) = sum over lists of 1 / (k + rank). Stable on ties."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: -kv[1])


class Retriever:
    """Top-k retrieval over the leaf chunks.

    ``hybrid``: dense (bge-m3) and BM25 rankings for every query variant are fused with RRF;
    the fused top ``candidate_k`` are then rescored by the cross-encoder when one is given.
    """

    def __init__(
        self,
        corpus: Corpus,
        embedder: EmbeddingProvider,
        store: VectorStore,
        *,
        mode: RetrievalMode = "dense",
        reranker: RerankerProvider | None = None,
        candidate_k: int = 30,
        rrf_k: int = 60,
        rerank_strategy: RerankStrategy = "fuse",
    ) -> None:
        self.corpus = corpus
        self._embedder = embedder
        self._store = store
        self.mode = mode
        self.reranker = reranker
        self._candidate_k = candidate_k
        self._rrf_k = rrf_k
        self.rerank_strategy = rerank_strategy
        self._units = corpus.retrieval_units()
        self._bm25 = (
            BM25Index([c.embed_text for c in self._units]) if mode in ("bm25", "hybrid") else None
        )

    @staticmethod
    def check_ready(corpus: Corpus, embedder: EmbeddingProvider, index_dir: Path) -> IndexMeta:
        """Fail fast if the index is missing, built with another model, or stale."""
        meta = IndexMeta.read(index_dir)
        if meta is None:
            raise IndexNotReadyError("No index found; run `python -m scripts.build_index`")
        if meta.embedding_model != embedder.model_name:
            raise IndexNotReadyError(
                f"Index was built with {meta.embedding_model}, configured model is "
                f"{embedder.model_name}; rebuild with `python -m scripts.build_index`"
            )
        if meta.corpus_fingerprint != corpus.fingerprint():
            raise IndexNotReadyError(
                "Corpus changed since the index was built; rebuild with "
                "`python -m scripts.build_index`"
            )
        return meta

    def _dense(self, query: str, limit: int) -> list[str]:
        return [h.chunk_id for h in self._store.search(self._embedder.embed_query(query), limit)]

    def _lexical(self, query: str, limit: int) -> list[str]:
        if self._bm25 is None:
            return []
        return [self._units[h.index].chunk_id for h in self._bm25.search(query, limit)]

    def search(
        self,
        query: str,
        top_k: int,
        *,
        alt_queries: Sequence[str] = (),
        rerank_query: str | None = None,
    ) -> list[RetrievedChunk]:
        """Retrieve for ``query`` plus ``alt_queries`` (e.g. an English translation).

        ``rerank_query`` (default ``query``) is what the cross-encoder compares passages with.
        """
        queries = [query, *(q for q in alt_queries if q and q != query)]
        pool = self._candidate_k if self.reranker is not None else top_k
        rankings: list[list[str]] = []
        for q in queries:
            if self.mode in ("dense", "hybrid"):
                rankings.append(self._dense(q, max(pool, top_k)))
            if self.mode in ("bm25", "hybrid"):
                rankings.append(self._lexical(q, max(pool, top_k)))
        fused = rrf_fuse(rankings, self._rrf_k)
        known = [(cid, s) for cid, s in fused if cid in self.corpus.chunks]
        if len(known) < len(fused):  # index/corpus mismatch; check_ready normally prevents it
            logger.warning("index_chunk_missing", missing=len(fused) - len(known))

        if self.reranker is not None and known:
            candidates = [self.corpus.chunks[cid] for cid, _ in known[:pool]]
            scores = self.reranker.score(rerank_query or query, [c.embed_text for c in candidates])
            by_rerank = sorted(zip(candidates, scores, strict=True), key=lambda cs: -cs[1])
            if self.rerank_strategy == "replace":
                return [
                    RetrievedChunk(chunk=c, score=s, rank=i)
                    for i, (c, s) in enumerate(by_rerank[:top_k], start=1)
                ]
            rerank_score = {c.chunk_id: s for c, s in by_rerank}
            final = rrf_fuse(
                [[c.chunk_id for c in candidates], [c.chunk_id for c, _ in by_rerank]],
                self._rrf_k,
            )
            return [  # score shown = cross-encoder relevance (0..1), order = fused
                RetrievedChunk(chunk=self.corpus.chunks[cid], score=rerank_score[cid], rank=i)
                for i, (cid, _) in enumerate(final[:top_k], start=1)
            ]
        return [
            RetrievedChunk(chunk=self.corpus.chunks[cid], score=s, rank=i)
            for i, (cid, s) in enumerate(known[:top_k], start=1)
        ]

    def close(self) -> None:
        self._store.close()
