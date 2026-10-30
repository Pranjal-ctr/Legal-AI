"""Judgment parser on synthetic pages shaped like Digital S.C.R. and High Court PDFs."""

from datetime import date

from app.ingestion.judgment import build_judgment, clean_pages
from app.ingestion.models import Page

LONG = " ".join(["The parties lived apart and the court considered the evidence on record."] * 4)

SCR_PAGES = [
    """[2024] 7 S.C.R. 933 : 2024 INSC 517
Vikas Kanaujia
v.
Sarita
(Civil Appeal No. 7380 of 2024)
10 July 2024
[Vikram Nath* and Satish Chandra Sharma, JJ.]
Issue for Consideration
Whether the marriage has irretrievably broken down.
Headnotes†
Marriage – Divorce – Article 142 – Held: decree of divorce granted.
List of Acts
Constitution of India; Hindu Marriage Act, 1955.
* Author""",
    f"""934 [2024] 7 S.C.R.
Digital Supreme Court Reports
Judgment / Order of the Supreme Court
Judgment
Vikram Nath, J.
1. Leave granted.
2. The appellant filed a petition under Section 13 of the Hindu Marriage Act, 1955. {LONG}
3. {LONG}""",
    f"""[2024] 7 S.C.R. 935
Vikas Kanaujia v. Sarita
4. {LONG}
Result of the case: Appeal allowed.
†Headnotes prepared by: Someone""",
]

HC_PAGES = [
    """- 1 -
NC: 2026:KHC:57008
IN THE HIGH COURT OF KARNATAKA AT BENGALURU
DATED THIS THE 8 TH DAY OF OCTOBER, 2026
CRL.P No. 3328 of 2024
BETWEEN:
1. SRI. ANJAN P
2. SRI. N. PURUSHOTHAM
...PETITIONERS
ORDER
1. This petition is filed under Section 482 of Cr.P.C. seeking to quash the complaint.""",
    f"""- 2 -
NC: 2026:KHC:57008
2. {LONG}
3. {LONG}
4. Petition allowed.""",
]


def pages(texts: list[str]) -> list[Page]:
    return [Page(number=i, text=t) for i, t in enumerate(texts, 1)]


def test_running_headers_removed() -> None:
    lines = [line.text for line in clean_pages(pages(HC_PAGES))]
    assert "NC: 2026:KHC:57008" not in lines
    assert "- 2 -" not in lines
    assert "IN THE HIGH COURT OF KARNATAKA AT BENGALURU" in lines


def test_supreme_court_report() -> None:
    document, chunks = build_judgment(pages(SCR_PAGES), "sc-abc", "supreme_court", ["divorce"], [])
    assert document.title == "Vikas Kanaujia v. Sarita"
    assert document.citation == "[2024] 7 S.C.R. 933 : 2024 INSC 517"
    assert document.case_number == "Civil Appeal No. 7380 of 2024"
    assert document.decision_date == date(2024, 7, 10)
    assert document.bench == "Vikram Nath* and Satish Chandra Sharma, JJ."
    assert document.result == "Appeal allowed."
    assert {"hma1955", "constitution"} <= set(document.statutes_cited)

    ids = [c.chunk_id for c in chunks]
    # "1. Leave granted." is too short to stand alone and merges into para 2.
    assert ids == ["sc-abc:issue", "sc-abc:headnotes", "sc-abc:p1-2", "sc-abc:p3", "sc-abc:p4"]
    p4 = chunks[-1]
    assert "Result of the case" not in p4.text and "Headnotes prepared" not in p4.text
    assert "Vikas Kanaujia v. Sarita" not in p4.text  # running title stripped
    assert p4.page_start == 3
    assert chunks[2].label == "Paras 1–2"
    assert "hma1955" in chunks[2].statutes_cited
    assert chunks[0].context.startswith("Supreme Court of India | Vikas Kanaujia v. Sarita")


def test_high_court_order_skips_party_list() -> None:
    document, chunks = build_judgment(pages(HC_PAGES), "hc-abc", "high_court", ["divorce"], [])
    assert document.court == "High Court of Karnataka"
    assert document.citation == "2026:KHC:57008"
    assert document.case_number == "CRL.P No. 3328 of 2024"
    assert document.decision_date == date(2026, 10, 8)
    ids = [c.chunk_id for c in chunks]
    assert ids[0] == "hc-abc:header"
    assert "SRI. ANJAN P" in chunks[0].text  # party list stays in the header, not as paras
    # A short final paragraph (usually the operative order) stays its own chunk.
    assert ids[1:] == ["hc-abc:p1-2", "hc-abc:p3", "hc-abc:p4"]


def test_long_paragraph_is_split() -> None:
    huge = " ".join([f"Sentence number {i} of a very long paragraph." for i in range(200)])
    texts = [f"1. {LONG}\n2. {huge}\n3. {LONG}"]
    _, chunks = build_judgment(pages(texts), "hc-x", "high_court", [], [])
    parts = [c for c in chunks if c.chunk_id.startswith("hc-x:p2.")]
    assert len(parts) > 1
    assert all(len(c.text) <= 2400 for c in parts)
    assert parts[0].label.startswith("Para 2 (part 1/")


def test_unnumbered_text_falls_back_to_windows() -> None:
    _, chunks = build_judgment(pages([LONG * 3]), "hc-y", "high_court", [], [])
    assert [c.chunk_id for c in chunks] == ["hc-y:text"]
