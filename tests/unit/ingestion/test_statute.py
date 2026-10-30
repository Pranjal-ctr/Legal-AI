"""Statute parser on a synthetic two-page Act laid out like the Legislative Department PDFs."""

import re

import pytest

from app.ingestion.models import Chunk, Page
from app.ingestion.statute import ActSpec, StatuteParseError, build_statute

SPEC = ActSpec(
    act_id="toy1999",
    title="The Toy Act, 1999",
    short_title="Toy Act, 1999",
    body_start=re.compile(r"^BE it enacted"),
    personal_law="hindu",
)

ARRANGEMENT = """THE TOY ACT, 1999
ARRANGEMENT OF SECTIONS
1. Short title.
2. Divorce.
1"""

PAGE_2 = """THE TOY ACT, 1999
[18th May, 1999.]
BE it enacted by Parliament as follows:—
PRELIMINARY
1. Short title.—This Act may be called the Toy Act, 1999.
GROUNDS
1[2. Divorce.—(1) Any marriage may be dissolved on the ground that the other party—
(i) has deserted the petitioner; or
2[(ia) has treated the petitioner with cruelty; or]
(ii) has ceased to be a Hindu; or
3* * * * *
(v) has been suffering from venereal disease; or
Explanation.—In this sub-section, the expression “desertion” means desertion
without reasonable cause.
(2) A wife may also present a petition on the ground,—
(a) that the husband has married again:
Provided that the other wife is alive; or
(b) that the husband has been guilty of rape, as referred to in clause
(c) of section 9.]
1. Subs. by Act 68 of 1976, s. 7 (w.e.f. 27-5-1976).
2. Ins. by s. 7, ibid. (w.e.f. 27-5-1976).
3. Clause (iv) omitted by Act 6 of 2019, s. 5 (w.e.f. 1-3-2019).
2"""

PAGE_3 = """3. Maintenance.—Where it appears to the court that either party has no income, it
may order the respondent to pay a reasonable sum.
1[Provided that the application shall be disposed of within sixty days.]
1. Ins. by Act 49 of 2001, s. 8 (w.e.f. 24-9-2001).
3"""


@pytest.fixture
def parsed() -> tuple[list[Chunk], dict[str, Chunk]]:
    pages = [Page(number=i, text=t) for i, t in enumerate([ARRANGEMENT, PAGE_2, PAGE_3], 1)]
    document, chunks = build_statute(pages, SPEC, [])
    assert document.enacted_on is not None and document.enacted_on.isoformat() == "1999-05-18"
    assert document.personal_law == "hindu"
    return chunks, {c.chunk_id: c for c in chunks}


def test_sections_and_hierarchical_ids(parsed: tuple[list[Chunk], dict[str, Chunk]]) -> None:
    chunks, by_id = parsed
    assert [c.chunk_id for c in chunks if c.kind == "section"] == [
        "toy1999:s1",
        "toy1999:s2",
        "toy1999:s3",
    ]
    provisions = [c.chunk_id for c in chunks if c.kind == "provision"]
    assert provisions == [
        "toy1999:s1:body",
        "toy1999:s2:ss1:cl(i)",
        "toy1999:s2:ss1:cl(ia)",
        "toy1999:s2:ss1:cl(ii)",
        "toy1999:s2:ss1:cl(v)",  # (iv) omitted: the gap is accepted
        "toy1999:s2:ss1:expl",
        "toy1999:s2:ss2:cl(a)",
        "toy1999:s2:ss2:cl(b)",
        "toy1999:s3:body",
    ]
    assert all(
        by_id[p].parent_id == p.rsplit(":", maxsplit=p.count(":") - 1)[0] for p in provisions
    )


def test_markers_removed_and_footnotes_attached(
    parsed: tuple[list[Chunk], dict[str, Chunk]],
) -> None:
    _, by_id = parsed
    ia = by_id["toy1999:s2:ss1:cl(ia)"]
    assert ia.text == "(ia) has treated the petitioner with cruelty; or"
    assert by_id["toy1999:s2"].amendments == [
        "Subs. by Act 68 of 1976, s. 7 (w.e.f. 27-5-1976).",
        "Ins. by s. 7, ibid. (w.e.f. 27-5-1976).",
        "Clause (iv) omitted by Act 6 of 2019, s. 5 (w.e.f. 1-3-2019).",
    ]
    # Footnote numbering restarts per page: page 3's "1." belongs to section 3.
    assert by_id["toy1999:s3"].amendments == ["Ins. by Act 49 of 2001, s. 8 (w.e.f. 24-9-2001)."]
    assert "]" not in by_id["toy1999:s2"].text
    assert "1. Subs." not in by_id["toy1999:s2"].text


def test_lead_in_goes_to_context(parsed: tuple[list[Chunk], dict[str, Chunk]]) -> None:
    _, by_id = parsed
    chunk = by_id["toy1999:s2:ss1:cl(i)"]
    assert chunk.label == "Section 2(1)(i)"
    assert "Toy Act, 1999 | GROUNDS | Section 2. Divorce" in chunk.context
    assert "on the ground that the other party—" in chunk.context
    assert chunk.embed_text.endswith("(i) has deserted the petitioner; or")


def test_proviso_and_wrapped_cross_reference(parsed: tuple[list[Chunk], dict[str, Chunk]]) -> None:
    _, by_id = parsed
    a = by_id["toy1999:s2:ss2:cl(a)"]
    assert a.text.endswith("Provided that the other wife is alive; or")
    # "(c) of section 9" wrapped onto its own line must not start a new clause.
    b = by_id["toy1999:s2:ss2:cl(b)"]
    assert b.text.endswith("as referred to in clause (c) of section 9.")


def test_unstructured_section_keeps_body_and_proviso(
    parsed: tuple[list[Chunk], dict[str, Chunk]],
) -> None:
    _, by_id = parsed
    body = by_id["toy1999:s3:body"].text
    assert body.startswith("Where it appears to the court")
    assert body.endswith("Provided that the application shall be disposed of within sixty days.")
    assert by_id["toy1999:s3:body"].page_start == 3


def test_no_sections_raises() -> None:
    with pytest.raises(StatuteParseError):
        build_statute([Page(number=1, text="nothing here")], SPEC, [])
