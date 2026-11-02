from app.retrieval.evaluation import GoldQuery, matches, score_query, summarise


def _gold(*expected: str) -> GoldQuery:
    return GoldQuery(
        id="g1",
        language="en",
        topic="t",
        query="q",
        expected_chunk_ids=list(expected),
        evidence="e",
        status="draft",
    )


def test_matches_exact_or_descendant_only() -> None:
    assert matches("act1:s13:ss1", "act1:s13:ss1")
    assert matches("act1:s13:ss1:cl(ia)", "act1:s13:ss1")
    assert not matches("act1:s13:ss10", "act1:s13:ss1")
    assert not matches("act1:s13", "act1:s13:ss1")


def test_score_query_rank_recall_and_doc_hit() -> None:
    result = score_query(_gold("a:x", "a:y"), ["b:z", "a:y", "a:w"])

    assert result.first_hit_rank == 2
    assert result.recall == 0.5
    assert result.doc_hit


def test_miss_with_right_document() -> None:
    result = score_query(_gold("a:x"), ["a:w", "b:z"])

    assert result.first_hit_rank is None
    assert result.recall == 0.0
    assert result.doc_hit


def test_summarise() -> None:
    results = [
        score_query(_gold("a:x"), ["a:x"]),  # rank 1
        score_query(_gold("a:x"), ["b:z", "a:x"]),  # rank 2
        score_query(_gold("a:x"), ["b:z"]),  # miss
        score_query(_gold("a:x"), ["a:q"]),  # right document, wrong chunk
    ]

    summary = summarise(results, k=2)

    assert summary.queries == 4
    assert summary.hit_rate == 0.5
    assert summary.doc_hit_rate == 0.75
    assert summary.mean_recall == 0.5
    assert summary.mrr == round((1 + 0.5) / 4, 4)
    assert summarise([], k=2).queries == 0
