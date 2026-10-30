"""Parse a court judgment PDF (Supreme Court Reports or High Court) into citable chunks.

Steps:
1. Drop running headers/footers: lines that repeat (digits ignored) at the top/bottom of many
   pages, page numbers, and the A-H margin letters of printed S.C.R. volumes.
2. Extract metadata best-effort from the first pages. Anything not found stays ``None`` — values
   are never guessed.
3. Reported (Digital S.C.R.) judgments: "Issue for Consideration" and "Headnotes" become summary
   chunks; the body starts at "Judgment / Order of the Supreme Court".
4. The body is split into numbered paragraphs: the longest chain of line-initial ``N.`` numbers
   increasing by one (this skips party lists such as "1. UNION OF INDIA 2. UNDER SECRETARY" and
   numbered lists quoted inside paragraphs). Short paragraphs merge with the next; long ones are
   split at sentence ends. Text before the chain is kept as a "Case header" chunk.
5. Without a usable chain the body falls back to fixed-size windows.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass

from app.ingestion.models import Chunk, ChunkKind, CourtLevel, Document, Page, SourceFile
from app.ingestion.text import clean_line, detect_statutes, join_lines, parse_date, split_long

MIN_PARAGRAPH_CHARS = 200
MIN_HEADER_CHARS = 80  # shorter pre-paragraph text ("Judgment / X, J.") joins paragraph 1
MAX_CHUNK_CHARS = 2400
TARGET_CHUNK_CHARS = 1600
EDGE_LINES = 4  # lines at the top/bottom of a page checked for running headers/footers
MAX_EDGE_CHARS = 120  # running headers/footers are short; long lines are body text

PAGE_NUMBER = re.compile(
    r"^[-–—\s]*(?:page\s*)?\d{1,4}(?:\s*of\s*\d{1,4})?[-–—\s]*$", re.IGNORECASE
)
MARGIN_LETTERS = re.compile(r"^(?:[A-H]\s+){2,}[A-H]$|^[A-H]$")
MARGIN_PREFIX = re.compile(r"^(?:[A-H]\s+){7}[A-H]\s+(?:\d{1,4}\s+)?")
ALWAYS_DROP = re.compile(
    r"^(?:Digital Supreme Court Reports|\* Author|†?Headnotes prepared by\b.*)$"
)
# S.C.R. page headers: "934 [2024] 7 S.C.R.", "[2024] 7 S.C.R. 935", "970 SUPREME COURT REPORTS ..."
SCR_PAGE_HEADER = re.compile(
    r"^(?:\d{1,4}\s+)?(?:SUPREME COURT REPORTS\s+)?"
    r"\[\d{4}\]\s*\d{1,2}\s*S\.\s?C\.\s?R\.(?:\s+\d{1,4})?$"
)
# "15. The..." and the Madras style "2.Learned Counsel" (no space before a capital).
PARAGRAPH_START = re.compile(r"^(\d{1,3})\.(?:\s+\S|(?=[A-Z(“\"‘\[])|$)")
# Printed S.C.R. volumes glue A-H margin letters onto lines: "TEJASWINI GAUD AND ORS. A".
MARGIN_TRAILING = re.compile(r"\s[A-H]$")
MARGIN_LEADING = re.compile(r"^(?:[B-H]\s(?=\S)|A\s(?=[A-Z]{2}|\d{1,3}\.))")

SCR_SECTIONS = (
    "Issue for Consideration",
    "Headnotes",
    "Case Law Cited",
    "List of Acts",
    "List of Keywords",
    "Case Arising From",
    "Appearances for Parties",
)
SCR_BODY_START = re.compile(r"^Judgment\s*/\s*Order of the Supreme Court$", re.IGNORECASE)
OLD_SCR_BODY_START = re.compile(r"^The Judgment of the Court was delivered by", re.IGNORECASE)

SCR_CITATION = re.compile(r"\[(\d{4})\]\s*(\d{1,2})\s*S\.\s?C\.\s?R\.\s*(\d{1,4})")
OLD_SCR_CITATION = re.compile(
    r"(\d{1,4})\s+SUPREME COURT REPORTS\s+\[(\d{4})\]\s*(\d{1,2})\s*S\.\s?C\.\s?R\."
)
INSC = re.compile(r"(\d{4})\s+INSC\s+(\d{1,5})")
NEUTRAL_CITATION = re.compile(r"\b(\d{4}):([A-Z]{2,6}):(\d{3,6})(?:-DB)?\b")
# First-page header of a printed volume, sometimes garbled by overprinting:
# "970 SUPREME COU[2R0T22 R] 5E PSO.CR.RT.S 970 [2022] 5 S.C.R."
GARBLED_SCR_HEADER = re.compile(r"^(\d{1,4})\b.*\[(\d{4})\]\s*(\d{1,2})\s*S\.\s?C\.\s?R\.\s*$")
SC_TITLE = re.compile(
    r"(?P<title>(?:[^()\[\]]|\([^()]*\))+?\sv\.?\s(?:[^()\[\]]|\([^()]*\))+?)\s*"
    r"\((?P<case>(?:[^()]|\([^()]*\))*?No(?:[^()]|\([^()]*\))*?)\)\s*"
    r"(?P<date>\d{1,2}\s+[A-Za-z]+\s+\d{4}|[A-Z]+\s+\d{1,2},\s*\d{4})\s*"
    r"\[(?P<bench>[^\]]+)\]"
)
RESULT = re.compile(r"^Result of the case:\s*(.+)$")
DATE_LABELS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"Date\s+of\s+Decision\s*:?\s*(.{6,40})",
        r"Decided\s+on\s*:?\s*(.{6,40})",
        r"Pronounced\s+on\s*:?\s*(.{6,40})",
        r"Delivered\s+on\s*:?\s*(.{6,40})",
        r"DATE\s+OF\s+JUDGMENT\s+PRONOUNCED\s*:?\s*(.{6,40})",
        r"DATED\s+THIS\s+THE\s+(.{6,40})",
        r"(?:ORDER|JUDGMENT)\s+DATED\s*:\s*(.{6,40})",
        r"\bDATED\s*:\s*(.{6,40})",
        r"(?:Judgment|Order)\s+on\s+Board\s*:?\s*(.{6,70})",  # "... Per X, Chief Justice <date>"
        r"\bTHE\s+(\d{1,2}\s*(?:ST|ND|RD|TH)\s+DAY\s+OF\s+[A-Z]+,?\s+\d{4})",
        r"\bdt\.\s*(.{6,20})",
    )
]
HC_COURT = [
    re.compile(
        r"HIGH\s+COURT\s+OF\s+(?:JUDICATURE\s+(?:AT|FOR)\s+)?([A-Z][A-Z ]+?)(?:\s+AT\b|,|$)"
    ),
    re.compile(r"\b([A-Z]{4,})\s+HIGH\s+COURT\b"),
]
NEUTRAL_COURT_CODES = {
    "KHC": "Karnataka",
    "CGHC": "Chhattisgarh",
    "HHC": "Himachal Pradesh",
    "DHC": "Delhi",
    "BHC": "Bombay",
    "PHHC": "Punjab and Haryana",
    "KER": "Kerala",
}
# Anchored at a line start: "CRMP No. 2617 of 2023", "WRIT PETITION (HABEAS CORPUS) NO.128 OF 2025".
CASE_NUMBER = re.compile(
    r"^((?:[A-Z(][A-Za-z.()&/-]*\s){0,6}[A-Z(][A-Za-z.()&/-]*\s?(?:No|NO)\.?\s*[:.]?\s*\d+\s*"
    r"(?:of|OF|/)\s*\d{4})"
)
_SMALL_WORDS = {"and", "of", "at", "for", "the"}


def _smart_title(text: str) -> str:
    words = text.lower().split()
    return " ".join(w if (i and w in _SMALL_WORDS) else w.capitalize() for i, w in enumerate(words))


@dataclass
class _Line:
    page: int
    text: str


def _edge_key(line: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", line.lower())).strip()


def clean_pages(pages: list[Page], edge_texts: frozenset[str] = frozenset()) -> list[_Line]:
    """Flatten pages to lines without running headers/footers, page numbers or margin letters.

    `edge_texts` are known running titles (e.g. the case title) dropped at page edges.
    """
    per_page = [[clean_line(raw) for raw in p.text.splitlines()] for p in pages]
    per_page = [[line for line in lines if line] for lines in per_page]

    counts: Counter[str] = Counter()
    for lines in per_page:
        edges = {
            _edge_key(line)
            for line in lines[:EDGE_LINES] + lines[-EDGE_LINES:]
            if len(line) <= MAX_EDGE_CHARS
        }
        counts.update(edges)
    threshold = max(2, math.ceil(0.3 * len(pages)))
    repeated = {key for key, n in counts.items() if n >= threshold} if len(pages) >= 2 else set()

    printed_scr = sum(bool(MARGIN_LETTERS.match(line)) for lines in per_page for line in lines) >= 3

    out: list[_Line] = []
    for page, lines in zip(pages, per_page, strict=True):
        for i, line in enumerate(lines):
            at_edge = i < EDGE_LINES or i >= len(lines) - EDGE_LINES
            if at_edge and (
                (len(line) <= MAX_EDGE_CHARS and _edge_key(line) in repeated)
                or PAGE_NUMBER.match(line)
                or SCR_PAGE_HEADER.match(line)
                or line in edge_texts
            ):
                continue
            if MARGIN_LETTERS.match(line) or ALWAYS_DROP.match(line):
                continue
            line = MARGIN_PREFIX.sub("", line)
            if printed_scr:
                line = MARGIN_LEADING.sub("", MARGIN_TRAILING.sub("", line))
            if line:
                out.append(_Line(page.number, line))
    return out


def _paragraph_chain(lines: list[_Line]) -> list[tuple[int, int]]:
    """Longest run of line-initial paragraph numbers (start <= 3), as (line idx, n).

    Each step is n -> n+1, or n -> n+2 when a number is missing (e.g. it starts mid-line).
    Equal-length chains are ranked by how much text their members own, i.e. the text from a
    numbered line up to the next numbered line (capped). Party lists ("1. UNION OF INDIA") and
    forms quoted inside a paragraph ("1. Name: 2. Age: ...") own a line each; real paragraphs
    own far more.
    """
    own_cap = 300
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line.text) + 1)
    candidates = [
        (i, int(m[1])) for i, line in enumerate(lines) if (m := PARAGRAPH_START.match(line.text))
    ]
    if not candidates:
        return []
    next_idx = [c[0] for c in candidates[1:]] + [len(lines)]
    own = [
        min(offsets[n] - offsets[c[0]], own_cap) for c, n in zip(candidates, next_idx, strict=True)
    ]
    score: list[tuple[int, int]] = []  # (chain length, text owned by its members)
    back: list[int] = []
    for k, (_, number) in enumerate(candidates):
        current, prev = ((1, own[k]) if number <= 3 else (0, 0)), -1
        for j in range(k):
            length, coverage = score[j]
            linkable = length > 0 and number - candidates[j][1] in (1, 2)
            if linkable and (length + 1, coverage + own[k]) > current:
                current, prev = (length + 1, coverage + own[k]), j
        score.append(current)
        back.append(prev)
    if not score or max(score)[0] == 0:
        return []
    end = max(range(len(score)), key=lambda k: (score[k], k))
    chain: list[tuple[int, int]] = []
    while end != -1:
        chain.append(candidates[end])
        end = back[end]
    return chain[::-1]


@dataclass
class _Meta:
    court: str | None = None
    citation: str | None = None
    case_number: str | None = None
    title: str | None = None
    decision_date_text: str | None = None
    bench: str | None = None
    result: str | None = None


def _sc_metadata(front: str) -> _Meta:
    meta = _Meta(court="Supreme Court of India")
    first_line = clean_line(front.splitlines()[0]) if front.strip() else ""
    flat = " ".join(front.split())
    flat = re.sub(r"(?<!\S)[A-H](?!\S)", " ", flat)  # margin letters of printed volumes
    citation = None
    if m := SCR_CITATION.search(flat):
        citation = f"[{m[1]}] {m[2]} S.C.R. {m[3]}"
    elif m := OLD_SCR_CITATION.search(flat):
        citation = f"[{m[2]}] {m[3]} S.C.R. {m[1]}"
    elif m := GARBLED_SCR_HEADER.match(first_line):
        citation = f"[{m[2]}] {m[3]} S.C.R. {m[1]}"
        flat = flat.replace(first_line, " ", 1)
    if m := INSC.search(flat):
        citation = f"{citation} : {m[1]} INSC {m[2]}" if citation else f"{m[1]} INSC {m[2]}"
    meta.citation = citation
    body = SCR_CITATION.sub(" ", INSC.sub(" ", OLD_SCR_CITATION.sub(" ", flat)))
    body = MARGIN_PREFIX.sub("", body.replace(":", " ").strip())
    if m := SC_TITLE.search(body):
        title = re.sub(r"^(?:\d{1,4}\s+)?(?:CASE DETAILS\s+)?", "", m["title"]).strip(" :")
        meta.title = " ".join(title.split())
        meta.case_number = m["case"].strip()
        meta.decision_date_text = m["date"]
        meta.bench = m["bench"].strip()
    return meta


def _hc_metadata(front: str) -> _Meta:
    meta = _Meta()
    lines = [clean_line(line) for line in front.splitlines()]
    for pattern in HC_COURT:
        for line in lines:
            if m := pattern.search(line.upper()):
                meta.court = f"High Court of {_smart_title(m[1])}"
                break
        if meta.court:
            break
    if m := NEUTRAL_CITATION.search(front):
        meta.citation = m[0]
        if meta.court is None and m[2] in NEUTRAL_COURT_CODES:
            meta.court = f"High Court of {NEUTRAL_COURT_CODES[m[2]]}"
    for i, line in enumerate(lines):
        m = CASE_NUMBER.search(line)
        if (
            m is None
            and re.search(r"\b(?:No|NO)\.?\s*\d+\s*(?:of|OF)?$", line)
            and i + 1 < len(lines)
        ):
            m = CASE_NUMBER.search(f"{line} {lines[i + 1]}")  # wrapped: "NO. 12282 of / 2026"
        if m:
            meta.case_number = clean_line(m[1])
            break
    for pattern in DATE_LABELS:
        if (m := pattern.search(" ".join(lines))) and parse_date(m[1]):
            meta.decision_date_text = m[1]
            break
    return meta


def _summary_blocks(lines: list[_Line]) -> dict[str, list[_Line]]:
    """Split S.C.R. front matter into labelled blocks (Issue for Consideration, Headnotes...)."""
    blocks: dict[str, list[_Line]] = {}
    current: str | None = None
    for line in lines:
        heading = line.text.rstrip("†* ").strip().lower()
        name = next((s for s in SCR_SECTIONS if heading == s.lower()), None)
        if name:
            current = name
            blocks[current] = []
        elif current:
            blocks[current].append(line)
    return blocks


def build_judgment(
    pages: list[Page],
    doc_id: str,
    court_level: CourtLevel,
    topics: list[str],
    sources: list[SourceFile],
) -> tuple[Document, list[Chunk]]:
    raw_front = "\n".join(p.text for p in pages[:2])
    meta = _sc_metadata(raw_front) if court_level == "supreme_court" else _hc_metadata(raw_front)
    lines = clean_pages(pages, frozenset({meta.title}) if meta.title else frozenset())

    result = next((m[1].strip() for line in lines if (m := RESULT.match(line.text))), None)
    lines = [line for line in lines if not RESULT.match(line.text)]

    # Split front matter from the judgment body.
    body_start = next(
        (i + 1 for i, line in enumerate(lines) if SCR_BODY_START.match(line.text)), None
    )
    if body_start is None:
        body_start = next(
            (i for i, line in enumerate(lines) if OLD_SCR_BODY_START.match(line.text)), 0
        )
    front, body = lines[:body_start], lines[body_start:]

    chain = _paragraph_chain(body)
    if len(chain) < 3:
        chain = []
    preamble = body[: chain[0][0]] if chain else []
    if court_level == "high_court" and chain and meta.decision_date_text is None:
        # Some HC orders put the date only in the header; retry on the cleaned preamble.
        retry = _hc_metadata("\n".join(line.text for line in preamble))
        meta.decision_date_text = retry.decision_date_text

    decision_date = parse_date(meta.decision_date_text) if meta.decision_date_text else None
    title = meta.title or (
        f"{meta.court or 'High Court'}: {meta.case_number}"
        if meta.case_number
        else f"{meta.court or 'Judgment'} ({doc_id})"
    )
    full_text = "\n".join(line.text for line in lines)
    document = Document(
        doc_id=doc_id,
        doc_type="judgment",
        court_level=court_level,
        title=title,
        court=meta.court,
        citation=meta.citation,
        case_number=meta.case_number,
        decision_date=decision_date,
        bench=meta.bench,
        result=result,
        topics=topics,
        statutes_cited=detect_statutes(full_text),
        page_count=len(pages),
        sources=sources,
    )

    header = " | ".join(
        part
        for part in (
            meta.court,
            title,
            meta.citation or meta.case_number,
            decision_date.isoformat() if decision_date else None,
        )
        if part
    )
    chunks: list[Chunk] = []

    def emit(
        suffix: str, kind: ChunkKind, label: str, block: list[_Line], text: str | None = None
    ) -> None:
        body_text = text if text is not None else join_lines([line.text for line in block])
        if not body_text.strip():
            return
        chunks.append(
            Chunk(
                chunk_id=f"{doc_id}:{suffix}",
                doc_id=doc_id,
                kind=kind,
                label=label,
                order=len(chunks),
                text=body_text,
                context=f"{header} | {label}",
                page_start=block[0].page,
                page_end=block[-1].page,
                statutes_cited=detect_statutes(body_text),
            )
        )

    def emit_split(suffix: str, kind: ChunkKind, label: str, block: list[_Line]) -> None:
        pieces = split_long(
            join_lines([line.text for line in block]), MAX_CHUNK_CHARS, TARGET_CHUNK_CHARS
        )
        if len(pieces) == 1:
            emit(suffix, kind, label, block, pieces[0])
            return
        for n, piece in enumerate(pieces, start=1):
            emit(f"{suffix}.{n}", kind, f"{label} (part {n}/{len(pieces)})", block, piece)

    blocks = _summary_blocks(front)
    if blocks:
        if issue := blocks.get("Issue for Consideration"):
            emit_split("issue", "judgment_summary", "Issue for Consideration", issue)
        if notes := blocks.get("Headnotes"):
            emit_split("headnotes", "judgment_summary", "Headnotes", notes)
    elif front and court_level == "supreme_court":  # printed S.C.R.: unlabelled headnotes
        emit_split("headnotes", "judgment_summary", "Headnotes", front)
    elif front:
        emit_split("header", "judgment_summary", "Case header", front)

    if not chain:
        emit_split("text", "judgment_paragraph", "Text", body)
        return document, chunks

    pending: list[_Line] = []
    if len(join_lines([line.text for line in preamble])) >= MIN_HEADER_CHARS:
        emit_split("header", "judgment_paragraph", "Case header", preamble)
    else:  # e.g. "Judgment / Vikram Nath, J." — folded into the first paragraph
        pending = list(preamble)
    bounds = [idx for idx, _ in chain] + [len(body)]
    pending_first: int | None = None
    for k, (start, number) in enumerate(chain):
        block = body[start : bounds[k + 1]]
        pending += block
        pending_first = number if pending_first is None else pending_first
        is_last = k == len(chain) - 1
        if len(join_lines([line.text for line in pending])) < MIN_PARAGRAPH_CHARS and not is_last:
            continue
        span = f"{pending_first}" if pending_first == number else f"{pending_first}-{number}"
        label = f"Para {span}" if pending_first == number else f"Paras {pending_first}–{number}"
        emit_split(f"p{span}", "judgment_paragraph", label, pending)
        pending, pending_first = [], None
    return document, chunks
