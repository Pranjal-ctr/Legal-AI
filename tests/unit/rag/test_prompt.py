from app.rag.prompt import (
    SYSTEM_PROMPT,
    assemble_evidence,
    build_prompt,
    check_citations,
    source_heading,
)
from app.retrieval.index import RetrievedChunk
from tests.fakes import make_corpus


def _hits(*ids: str) -> list[RetrievedChunk]:
    corpus = make_corpus()
    return [
        RetrievedChunk(chunk=corpus.chunks[cid], score=1.0 - i / 10, rank=i + 1)
        for i, cid in enumerate(ids)
    ]


def test_provisions_map_to_their_section_once_in_rank_order() -> None:
    evidence = assemble_evidence(make_corpus(), _hits("sc-test:p4", "act1:s2:ss2", "act1:s2:ss1"))

    assert [(e.n, e.unit.chunk_id) for e in evidence] == [(1, "sc-test:p4"), (2, "act1:s2")]
    assert evidence[1].matched_chunk_ids == ["act1:s2:ss2", "act1:s2:ss1"]
    assert evidence[1].score == 0.9  # best (first) hit for that section


def test_headings_and_prompt_carry_verbatim_text() -> None:
    evidence = assemble_evidence(make_corpus(), _hits("act1:s2:ss1", "sc-test:p4"))

    assert source_heading(evidence[0]) == "Example Act, 2000 — Section 2"
    assert source_heading(evidence[1]) == (
        "A v. B, Supreme Court of India, [2024] 1 S.C.R. 1, decided 2024-01-02 — Para 4"
    )
    prompt = build_prompt("What grounds?", evidence)
    assert "[1] Example Act, 2000 — Section 2\n2. Grounds.— (1) alpha" in prompt
    assert "[2] A v. B" in prompt
    assert "QUESTION: What grounds?" in prompt
    assert prompt.rstrip().endswith("Answer using only the sources.")


def test_system_prompt_forbids_outside_knowledge_and_requires_citations() -> None:
    assert "ONLY the numbered SOURCES" in SYSTEM_PROMPT
    assert "Never invent" in SYSTEM_PROMPT


def test_valid_citations_are_kept_in_first_mention_order() -> None:
    check = check_citations("B applies [2]. A applies [1][2]. Both [1, 2].", source_count=2)

    assert check.cited == [2, 1]
    assert check.invalid == []
    assert check.answer == "B applies [2]. A applies [1][2]. Both [1][2]."


def test_out_of_range_citations_are_removed() -> None:
    check = check_citations("Claim [7]. Other [1; 9].", source_count=3)

    assert check.cited == [1]
    assert check.invalid == [7, 9]
    assert check.answer == "Claim. Other [1]."


def test_answer_without_citations() -> None:
    check = check_citations("The sources do not say.", source_count=3)

    assert (check.cited, check.invalid, check.answer) == ([], [], "The sources do not say.")
