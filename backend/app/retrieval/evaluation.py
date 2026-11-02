"""Retrieval metrics against the gold queries (``data/evaluation/gold_queries.jsonl``)."""

from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel


class GoldQuery(BaseModel):
    id: str
    language: str
    topic: str
    query: str
    expected_chunk_ids: list[str]
    evidence: str
    status: str
    source_id: str | None = None  # translated queries: id of the English original


def load_gold(path: Path) -> list[GoldQuery]:
    with path.open(encoding="utf-8") as fh:
        return [GoldQuery.model_validate_json(line) for line in fh if line.strip()]


def matches(retrieved_id: str, expected_id: str) -> bool:
    """Exact id, or a descendant of the expected id (e.g. ``s13:ss1`` covers ``s13:ss1:cl(ia)``)."""
    return retrieved_id == expected_id or retrieved_id.startswith(expected_id + ":")


def doc_of(chunk_id: str) -> str:
    """Chunk ids are ``<doc_id>:<locator>`` (ADR 0002)."""
    return chunk_id.split(":", 1)[0]


class QueryResult(BaseModel):
    id: str
    query: str
    expected: list[str]
    retrieved: list[str]
    first_hit_rank: int | None  # 1-based rank of the first relevant chunk
    doc_hit: bool  # a chunk from an expected document is in the top k (looser than chunk hit)
    recall: float  # share of expected ids found in the top k


def score_query(gold: GoldQuery, retrieved: Sequence[str]) -> QueryResult:
    found = [e for e in gold.expected_chunk_ids if any(matches(r, e) for r in retrieved)]
    first = next(
        (
            rank
            for rank, r in enumerate(retrieved, start=1)
            if any(matches(r, e) for e in gold.expected_chunk_ids)
        ),
        None,
    )
    expected_docs = {doc_of(e) for e in gold.expected_chunk_ids}
    return QueryResult(
        id=gold.id,
        query=gold.query,
        expected=gold.expected_chunk_ids,
        retrieved=list(retrieved),
        first_hit_rank=first,
        doc_hit=any(doc_of(r) in expected_docs for r in retrieved),
        recall=len(found) / len(gold.expected_chunk_ids),
    )


class EvalSummary(BaseModel):
    k: int
    queries: int
    hit_rate: float  # share of queries with >= 1 relevant chunk in the top k
    doc_hit_rate: float  # share of queries with >= 1 chunk from a relevant document
    mean_recall: float
    mrr: float


def summarise(results: Sequence[QueryResult], k: int) -> EvalSummary:
    n = len(results)
    if n == 0:
        return EvalSummary(k=k, queries=0, hit_rate=0.0, doc_hit_rate=0.0, mean_recall=0.0, mrr=0.0)
    return EvalSummary(
        k=k,
        queries=n,
        hit_rate=round(sum(r.first_hit_rank is not None for r in results) / n, 4),
        doc_hit_rate=round(sum(r.doc_hit for r in results) / n, 4),
        mean_recall=round(sum(r.recall for r in results) / n, 4),
        mrr=round(sum(1 / r.first_hit_rank for r in results if r.first_hit_rank) / n, 4),
    )
