import asyncio

from app.agents.evaluation import percentile, score_result, summarise
from app.retrieval.evaluation import GoldQuery
from tests.fakes import make_orchestrator, scripted_llm


def _gold(expected: str, evidence: str = "alpha grounds apply") -> GoldQuery:
    return GoldQuery(
        id="t1",
        language="en",
        topic="divorce",
        query="what alpha grounds apply",
        expected_chunk_ids=[expected],
        evidence=evidence,
        status="test",
    )


def _result():  # type: ignore[no-untyped-def]
    llm = scripted_llm(answer='The Act says "alpha grounds apply" [1].')
    return asyncio.run(make_orchestrator(llm).answer("what alpha grounds apply"))


def test_cited_parent_section_counts_as_hit_for_its_provision() -> None:
    result = _result()

    row = score_result(_gold("act1:s2:ss1"), result, ms=1200, clarified=False)

    assert row.kind == "answer"
    assert row.retrieval_hit and row.citation_hit
    assert row.evidence_cited  # the cited section contains the evidence text
    assert row.verified_quotes == 1 and row.unquoted == 0
    assert "retrieve_1" in row.steps


def test_miss_when_expected_source_absent() -> None:
    row = score_result(_gold("other:s9", "never said"), _result(), ms=1, clarified=True)

    assert not row.retrieval_hit and not row.citation_hit and not row.evidence_cited
    assert row.clarified


def test_summary_rates_and_latency() -> None:
    result = _result()
    rows = [
        score_result(_gold("act1:s2:ss1"), result, ms=1000, clarified=False),
        score_result(_gold("other:s9", "x"), result, ms=3000, clarified=True),
    ]

    summary = summarise(rows)

    assert summary["answered"] == 2
    assert summary["citation_hit"] == 0.5
    assert summary["clarified_rate"] == 0.5
    assert summary["latency_ms"] == {"p50": 1000.0, "p95": 3000.0, "max": 3000}
    assert percentile([], 50) == 0.0


def test_doc_level_hit_and_rescore() -> None:
    from app.agents.evaluation import doc_hit, rescore

    assert doc_hit(["sc-1:p9"], ["sc-1:issue"])
    assert not doc_hit(["sc-2:p9"], ["sc-1:issue"])

    row = score_result(_gold("act1:s9"), _result(), ms=1, clarified=False)
    assert not row.citation_hit and row.doc_cited  # same act, different section

    again = rescore(row.model_copy(update={"doc_cited": False}), _gold("act1:s9"))
    assert again.doc_cited and again.expected == ["act1:s9"]
