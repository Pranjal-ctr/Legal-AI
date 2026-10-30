"""Text helpers and corpus discovery (duplicate collapsing)."""

from datetime import date
from pathlib import Path

import pytest

from app.ingestion.corpus import discover_judgments
from app.ingestion.text import detect_statutes, join_lines, parse_date, split_long


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Date of Decision: 18.09.2026", date(2026, 9, 18)),
        ("27  .10  .2026", date(2026, 10, 27)),
        ("27/10/2026", date(2026, 10, 27)),
        ("THE 30 TH  DAY OF JUNE, 2026", date(2026, 6, 30)),
        ("1st SEPTEMBER 2026", date(2026, 9, 1)),
        ("MAY 06, 2019", date(2019, 5, 6)),
        ("10 July 2024", date(2024, 7, 10)),
        ("no date here", None),
        ("31.02.2026", None),
    ],
)
def test_parse_date(text: str, expected: date | None) -> None:
    assert parse_date(text) == expected


def test_join_lines_rejoins_hyphenated_wraps() -> None:
    assert join_lines(["notwithstanding sub-", "section (1) of the", "Act"]) == (
        "notwithstanding sub-section (1) of the Act"
    )


def test_detect_statutes() -> None:
    text = "under Section 125 Cr.P.C. and Section 13 of the Hindu Marriage Act, 1955"
    assert detect_statutes(text) == ["hma1955", "crpc1973"]


def test_split_long_respects_limits() -> None:
    text = " ".join(f"Sentence {i} ends here." for i in range(300))
    pieces = split_long(text, max_chars=500, target_chars=300)
    assert all(len(p) <= 500 for p in pieces)
    assert " ".join(pieces) == text


def test_discover_collapses_duplicates(tmp_path: Path) -> None:
    for folder, topic, content in [
        ("supreme court judgements", "divorce", b"%PDF same"),
        ("supreme court judgements", "domestic_violence", b"%PDF same"),
        ("high court judgements", "maintainence", b"%PDF other"),
    ]:
        target = tmp_path / folder / topic
        target.mkdir(parents=True)
        (target / "a.pdf").write_bytes(content)

    entries = discover_judgments(tmp_path, tmp_path)
    assert len(entries) == 2
    hc, sc = entries
    assert hc.court_level == "high_court" and hc.topics == ["maintenance"]
    assert sc.topics == ["divorce", "domestic_violence"]
    assert len(sc.sources) == 2 and sc.doc_id.startswith("sc-")
