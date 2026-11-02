from pathlib import Path

import pytest

from app.retrieval.bm25 import BM25Index, tokenize
from app.retrieval.index import Retriever, build_index, rrf_fuse
from tests.fakes import FakeEmbedder, FakeReranker, make_corpus, make_store


def test_tokenize_drops_stop_words_folds_plurals_and_keeps_indic_scripts() -> None:
    assert tokenize("What are the Grounds for divorce?") == ["ground", "divorce"]
    assert tokenize("Section 498A, cl. (ia)") == ["section", "498a", "cl", "ia"]
    assert tokenize("class address") == ["class", "address"]  # "ss" endings kept
    assert tokenize("तलाक के आधार") == ["तलाक", "के", "आधार"]
    assert tokenize("ವಿಚ್ಛೇದನ") != []


def test_bm25_ranks_rare_term_matches_first() -> None:
    index = BM25Index(
        [
            "the court considered maintenance",
            "cruelty is a ground for divorce",
            "maintenance and custody of the child",
        ]
    )

    hits = index.search("cruelty divorce", limit=5)

    assert len(index) == 3
    assert [h.index for h in hits] == [1]
    assert index.search("unknownword", limit=5) == []
    assert [h.index for h in index.search("maintenance", limit=1)] in ([0], [2])


def test_bm25_prefers_shorter_document_for_same_term_frequency() -> None:
    index = BM25Index(["custody", "custody of a child with many other unrelated words here"])

    assert [h.index for h in index.search("custody", limit=2)] == [0, 1]


def test_rrf_rewards_agreement_between_rankings() -> None:
    fused = rrf_fuse([["a", "b", "c"], ["b", "c", "a"]], k=60)

    assert [cid for cid, _ in fused] == ["b", "a", "c"]
    assert fused[0][1] == pytest.approx(1 / 62 + 1 / 61)
    assert rrf_fuse([]) == []


def _retriever(tmp_path: Path, **kwargs: object) -> Retriever:
    corpus, embedder, store = make_corpus(), FakeEmbedder(), make_store()
    build_index(corpus, embedder, store, tmp_path)
    return Retriever(corpus, embedder, store, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("mode", ["dense", "bm25", "hybrid"])
def test_every_mode_finds_the_matching_chunk(tmp_path: Path, mode: str) -> None:
    hits = _retriever(tmp_path, mode=mode).search("delta custody", top_k=3)

    assert hits[0].chunk.doc_id == "sc-test"
    assert [h.rank for h in hits] == list(range(1, len(hits) + 1))


def test_bm25_mode_returns_only_lexical_matches(tmp_path: Path) -> None:
    hits = _retriever(tmp_path, mode="bm25").search("gamma registration", top_k=5)

    assert [h.chunk.chunk_id for h in hits] == ["act1:s3"]


def test_replace_strategy_uses_cross_encoder_order(tmp_path: Path) -> None:
    reranker = FakeReranker()
    retriever = _retriever(
        tmp_path, mode="hybrid", reranker=reranker, candidate_k=5, rerank_strategy="replace"
    )

    hits = retriever.search("beta waiting period", top_k=2)

    assert hits[0].chunk.chunk_id == "act1:s2:ss2"
    assert hits[0].score == 1.0  # FakeReranker: all query words present
    assert len(hits) == 2
    assert reranker.calls == [("beta waiting period", 5)]


def test_fuse_strategy_needs_agreement_between_stages(tmp_path: Path) -> None:
    retriever = _retriever(tmp_path, mode="hybrid", reranker=FakeReranker(), candidate_k=5)
    first_stage = _retriever(tmp_path, mode="hybrid").search("beta waiting period", top_k=5)

    hits = retriever.search("beta waiting period", top_k=5)

    # The chunk ranked first by both stages stays first; scores shown are the reranker's.
    assert first_stage[0].chunk.chunk_id == hits[0].chunk.chunk_id == "act1:s2:ss2"
    assert hits[0].score == 1.0
    assert {h.chunk.chunk_id for h in hits} == {h.chunk.chunk_id for h in first_stage}


def test_alt_queries_are_fused_and_rerank_query_is_used(tmp_path: Path) -> None:
    reranker = FakeReranker()
    retriever = _retriever(tmp_path, mode="hybrid", reranker=reranker, candidate_k=5)

    hits = retriever.search(
        "ಡೆಲ್ಟಾ ಕಸ್ಟಡಿ",  # non-English query: BM25 finds nothing for it
        top_k=1,
        alt_queries=["delta custody"],
        rerank_query="delta custody",
    )

    assert hits[0].chunk.doc_id == "sc-test"
    assert reranker.calls[0][0] == "delta custody"
