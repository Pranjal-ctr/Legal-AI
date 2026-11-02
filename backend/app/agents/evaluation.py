"""End-to-end answer metrics against the gold queries (Phase 13, ``scripts/eval_e2e.py``).

Retrieval-only scores live in ``app.retrieval.evaluation``; these score what the user sees:
did the answer cite the right source, does a cited source contain the gold evidence, did every
quotation survive verbatim validation, did the translation keep its citations, and how long it
took. No LLM judge: every metric is computed from the result and the gold data.
"""

import math
import re
from collections.abc import Sequence
from statistics import median

from pydantic import BaseModel

from app.agents.orchestrator import ChatResult
from app.retrieval.evaluation import GoldQuery, doc_of, matches

_SPACE = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _SPACE.sub(" ", text).strip().lower()


class E2EResult(BaseModel):
    id: str
    language: str  # gold language
    detected_language: str
    query: str
    kind: str  # final turn: answer | clarification | out_of_scope
    clarified: bool  # the first turn asked a clarifying question (auto-answered)
    retrieval_hit: bool  # an expected chunk was among the sources given to the LLM
    citation_hit: bool  # ... and the answer cited it
    doc_cited: bool = False  # the answer cited the expected document (any passage of it)
    evidence_cited: bool  # a cited source contains the gold evidence text verbatim
    grounded: bool
    invalid_citations: int
    verified_quotes: int
    unquoted: int  # quotation marks removed because the text was not verbatim
    regenerated: bool
    translation_ok: bool
    rounds: int
    ms: int  # final turn, wall clock
    steps: dict[str, int]
    cited_ids: list[str]
    expected: list[str] = []
    answer_en: str
    answer: str


def _ids(item_unit_id: str, matched: Sequence[str]) -> list[str]:
    return [item_unit_id, *matched]


def _hit(ids: Sequence[str], expected: Sequence[str]) -> bool:
    """A chunk id matches an expected id, or is the parent unit containing it (a section)."""
    return any(matches(i, e) or matches(e, i) for i in ids for e in expected)


def doc_hit(ids: Sequence[str], expected: Sequence[str]) -> bool:
    """Looser than a citation hit: any passage of an expected document. Judgment questions often
    have several paragraphs that state the same holding; the gold names only one."""
    return bool({doc_of(i) for i in ids} & {doc_of(e) for e in expected})


def rescore(row: E2EResult, gold: GoldQuery) -> E2EResult:
    """Recompute the gold-derived fields of a stored result (no LLM): for metric changes."""
    return row.model_copy(
        update={
            "expected": list(gold.expected_chunk_ids),
            "doc_cited": doc_hit(row.cited_ids, gold.expected_chunk_ids),
        }
    )


def score_result(gold: GoldQuery, result: ChatResult, ms: int, clarified: bool) -> E2EResult:
    cited = set(result.cited)
    all_ids = [i for e in result.evidence for i in _ids(e.unit.chunk_id, e.matched_chunk_ids)]
    cited_items = [e for e in result.evidence if e.n in cited]
    cited_ids = [i for e in cited_items for i in _ids(e.unit.chunk_id, e.matched_chunk_ids)]
    evidence = _norm(gold.evidence)
    steps: dict[str, int] = {}
    for step in result.trace:
        steps[step.step] = steps.get(step.step, 0) + step.ms
    v = result.validation
    return E2EResult(
        id=gold.id,
        language=gold.language,
        detected_language=result.language,
        query=gold.query,
        kind=result.kind,
        clarified=clarified,
        retrieval_hit=_hit(all_ids, gold.expected_chunk_ids),
        citation_hit=_hit(cited_ids, gold.expected_chunk_ids),
        doc_cited=doc_hit(cited_ids, gold.expected_chunk_ids),
        evidence_cited=any(evidence in _norm(e.unit.text) for e in cited_items),
        grounded=result.grounded,
        invalid_citations=len(v.invalid_citations),
        verified_quotes=v.verified_quotes,
        unquoted=len(v.unquoted),
        regenerated=v.regenerated,
        translation_ok=v.translation_ok,
        rounds=result.rounds,
        ms=ms,
        steps=steps,
        cited_ids=sorted({e.unit.chunk_id for e in cited_items}),
        expected=list(gold.expected_chunk_ids),
        answer_en=result.answer_en,
        answer=result.answer,
    )


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile (q in 0..100); 0 for no values."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return float(ordered[rank - 1])


def _rate(rows: Sequence[E2EResult], attr: str) -> float | None:
    """Share of rows where ``attr`` is true; None when there are no rows to rate."""
    return round(sum(bool(getattr(r, attr)) for r in rows) / len(rows), 3) if rows else None


def summarise(rows: Sequence[E2EResult]) -> dict[str, object]:
    """Rates over all queries; quality rates are over answered queries only."""
    answered = [r for r in rows if r.kind == "answer"]
    translated = [r for r in answered if r.language != "en"]
    ms = [r.ms for r in answered]
    step_names = sorted({s for r in answered for s in r.steps})
    return {
        "n": len(rows),
        "answered": len(answered),
        "out_of_scope": sum(r.kind == "out_of_scope" for r in rows),
        "clarified_rate": _rate(rows, "clarified"),
        "language_detected_ok": round(
            sum(r.detected_language == r.language for r in rows) / len(rows), 3
        )
        if rows
        else 0.0,
        "retrieval_hit": _rate(answered, "retrieval_hit"),
        "citation_hit": _rate(answered, "citation_hit"),
        "doc_cited": _rate(answered, "doc_cited"),
        "evidence_cited": _rate(answered, "evidence_cited"),
        "grounded": _rate(answered, "grounded"),
        "invalid_citation_answers": sum(r.invalid_citations > 0 for r in answered),
        "answers_with_unquoted": sum(r.unquoted > 0 for r in answered),
        "verified_quotes_per_answer": round(
            sum(r.verified_quotes for r in answered) / len(answered), 2
        )
        if answered
        else 0.0,
        "regenerated": sum(r.regenerated for r in answered),
        "translation_ok": _rate(translated, "translation_ok"),
        "two_round_answers": sum(r.rounds > 1 for r in answered),
        "latency_ms": {
            "p50": percentile(ms, 50),
            "p95": percentile(ms, 95),
            "max": max(ms, default=0),
        },
        "step_median_ms": {
            s: int(median([r.steps[s] for r in answered if s in r.steps])) for s in step_names
        },
    }
