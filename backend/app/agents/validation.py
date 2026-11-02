"""Deterministic answer checks: verbatim quotations and citation markers after translation."""

import re
from collections import Counter
from dataclasses import dataclass

# Straight or curly double quotes; at least 2 words inside (single quoted words are emphasis).
_QUOTE_RE = re.compile(r"[\"“]([^\"“”\n]{3,400}?)[\"”]")
_MARKER_RE = re.compile(r"\[(\d+)\]")
_SPACE_RE = re.compile(r"\s+")
_ELLIPSIS_RE = re.compile(r"\.{3}|…")


def _norm(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("—", "-").replace("–", "-")
    return _SPACE_RE.sub(" ", text).strip().lower()


@dataclass(frozen=True)
class QuoteCheck:
    answer: str
    verified: list[str]  # quotations found verbatim in the sources
    unquoted: list[str]  # quotations NOT found: their quote marks were removed


def check_quotes(answer: str, source_texts: list[str]) -> QuoteCheck:
    """Quotations must be verbatim source text; non-verbatim ones lose their quote marks.

    Matching ignores case, whitespace and dash/apostrophe style, and tolerates leading or
    trailing punctuation. An ellipsis inside a quote marks omitted words: every fragment
    between ellipses must itself be verbatim.
    """
    corpus = _norm("\n".join(source_texts))
    verified: list[str] = []
    unquoted: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        inner = match.group(1)
        core = _norm(inner).strip(" .,;:…'")
        if len(core.split()) < 2:  # a single quoted word is emphasis, not a quotation
            return match.group(0)
        if is_verbatim(core, corpus):
            verified.append(inner)
            return match.group(0)
        unquoted.append(inner)
        return inner

    return QuoteCheck(_QUOTE_RE.sub(_replace, answer), verified, unquoted)


def is_verbatim(quote: str, normalised_corpus: str) -> bool:
    fragments = [f.strip(" .,;:'") for f in _ELLIPSIS_RE.split(_norm(quote))]
    fragments = [f for f in fragments if f]
    return bool(fragments) and all(f in normalised_corpus for f in fragments)


def restore_quotes(translated: str, answer_en: str, source_texts: list[str]) -> str:
    """Put the exact English law text back where a translation translated a quotation.

    The k-th quotation of the translation corresponds to the k-th quotation of the verified
    English answer. A translated quotation that is not verbatim source text becomes
    ``"<English quotation>" (<translation>)``, so users see the canonical wording and its
    meaning. If the quotation counts differ, non-verbatim quotations are simply unquoted.
    """
    corpus = _norm("\n".join(source_texts))
    english_quotes = [m.group(1) for m in _QUOTE_RE.finditer(answer_en)]
    translated_quotes = list(_QUOTE_RE.finditer(translated))
    paired = len(english_quotes) == len(translated_quotes)
    out: list[str] = []
    last = 0
    for k, match in enumerate(translated_quotes):
        out.append(translated[last : match.start()])
        inner = match.group(1)
        if is_verbatim(inner, corpus) or (len(_norm(inner).split()) < 2 and not paired):
            out.append(match.group(0))
        elif paired:
            out.append(f'"{english_quotes[k]}" ({inner})')
        else:
            out.append(inner)
        last = match.end()
    out.append(translated[last:])
    return "".join(out)


def markers(text: str) -> Counter[int]:
    return Counter(int(n) for n in _MARKER_RE.findall(text))


def markers_preserved(original: str, translated: str) -> bool:
    """Every [n] of the English answer survives translation (same numbers, same counts)."""
    return markers(original) == markers(translated)
