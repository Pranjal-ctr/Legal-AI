"""Text helpers shared by the statute and judgment parsers."""

import re
import unicodedata
from datetime import date

_SPACES = re.compile(r"[ \t  -​]+")


def clean_line(line: str) -> str:
    """Normalise whitespace and unicode compatibility forms; never changes words."""
    line = unicodedata.normalize("NFC", line).replace("�", "")
    return _SPACES.sub(" ", line).strip()


def join_lines(lines: list[str]) -> str:
    """Join wrapped PDF lines into running text; a trailing hyphen joins without a space."""
    out = ""
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if not out:
            out = line
        elif (out.endswith("-") and not out.endswith(" -")) or out.endswith("—"):
            out += line
        else:
            out += " " + line
    return out


# Acts we recognise in text. Keys are the stable ids stored in `statutes_cited`.
ACT_PATTERNS: dict[str, re.Pattern[str]] = {
    "hma1955": re.compile(r"Hindu\s+Marriage\s+Act|\bH\.?M\.?A\b"),
    "sma1954": re.compile(r"Special\s+Marriage\s+Act"),
    "hama1956": re.compile(r"Hindu\s+Adoptions?\s+and\s+Maintenance\s+Act"),
    "hmga1956": re.compile(r"Hindu\s+Minority\s+and\s+Guardianship\s+Act"),
    "gwa1890": re.compile(r"Guardians\s+and\s+Wards\s+Act"),
    "pwdva2005": re.compile(
        r"Protection\s+of\s+Women\s+from\s+Domestic\s+Violence\s+Act|\bD\.?V\.?\s+Act\b|\bPWDVA\b"
    ),
    "dpa1961": re.compile(r"Dowry\s+Prohibition\s+Act"),
    "crpc1973": re.compile(r"Code\s+of\s+Criminal\s+Procedure|\bCr\.?\s?P\.?\s?C\b"),
    "bnss2023": re.compile(r"Bharatiya\s+Nagarik\s+Suraksha\s+Sanhita|\bBNSS\b"),
    "ipc1860": re.compile(r"Indian\s+Penal\s+Code|\bI\.?P\.?C\b"),
    "bns2023": re.compile(r"Bharatiya\s+Nyaya\s+Sanhita|\bBNS\b"),
    "fca1984": re.compile(r"Family\s+Courts\s+Act"),
    "ida1869": re.compile(r"Indian\s+Divorce\s+Act|\bDivorce\s+Act,\s+1869"),
    "mwa1986": re.compile(r"Muslim\s+Women\s+\(Protection\s+of\s+Rights\s+on\s+Divorce\)"),
    "mwa2019": re.compile(r"Muslim\s+Women\s+\(Protection\s+of\s+Rights\s+on\s+Marriage\)"),
    "constitution": re.compile(
        r"Constitution\s+of\s+India|\bArticle\s+(?:14|15|21|32|136|142|226|227)\b"
    ),
}


def detect_statutes(text: str) -> list[str]:
    return [act_id for act_id, pattern in ACT_PATTERNS.items() if pattern.search(text)]


_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}

_NUMERIC_DATE = re.compile(r"(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{4})")
_DAY_MONTH_YEAR = re.compile(
    r"(\d{1,2})\s*(?:st|nd|rd|th)?\s*(?:day\s+of\s+)?([A-Za-z]{3,9})\.?,?\s+(\d{4})", re.IGNORECASE
)
_MONTH_DAY_YEAR = re.compile(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),\s*(\d{4})")


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_date(text: str) -> date | None:
    """Parse the first date in `text`.

    Handles 18.09.2026, 27/10/2026, "9TH DAY OF OCTOBER, 2026" and "MAY 06, 2019".
    """
    candidates: list[tuple[int, date]] = []
    for m in _NUMERIC_DATE.finditer(text):
        d = _safe_date(int(m[3]), int(m[2]), int(m[1]))
        if d:
            candidates.append((m.start(), d))
    for m in _DAY_MONTH_YEAR.finditer(text):
        month = _MONTHS.get(m[2].lower())
        d = _safe_date(int(m[3]), month, int(m[1])) if month else None
        if d:
            candidates.append((m.start(), d))
    for m in _MONTH_DAY_YEAR.finditer(text):
        month = _MONTHS.get(m[1].lower())
        d = _safe_date(int(m[3]), month, int(m[2])) if month else None
        if d:
            candidates.append((m.start(), d))
    return min(candidates, key=lambda c: c[0])[1] if candidates else None


_SENTENCE_END = re.compile(r"(?<=[.?!;:])\s+(?=[(\"“‘A-Z0-9])")


def split_long(text: str, max_chars: int, target_chars: int) -> list[str]:
    """Split text longer than `max_chars` into pieces of about `target_chars` at sentence ends."""
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        if current and len(current) + 1 + len(sentence) > target_chars:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}" if current else sentence
    if current:
        pieces.append(current)
    # A single giant "sentence" (e.g. a table) is hard-split so no piece exceeds max_chars.
    out: list[str] = []
    for piece in pieces:
        while len(piece) > max_chars:
            cut = piece.rfind(" ", 0, target_chars)
            cut = cut if cut > 0 else target_chars
            out.append(piece[:cut].strip())
            piece = piece[cut:].strip()
        out.append(piece)
    return [p for p in out if p]
