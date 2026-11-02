"""Turn an answer into text a TTS voice can read (Phase 10).

MMS voices know only letters (and a few digits) of their language: no punctuation, no Latin
script for hi/kn. So: citation markers go, quoted English law text that is followed by its
translation keeps only the translation, numbers become words, and the text is split into
clauses (the pause between clauses replaces punctuation).
"""

import re

from app.nlp.language import Language

_MARKERS = re.compile(r"\s*\[\d+\](?:\s*,?\s*\[\d+\])*")
# "<English law text>" (<translation>)  →  <translation>      (from restore_quotes)
_QUOTE_WITH_TRANSLATION = re.compile(r"[\"“][^\"“”]*[A-Za-z][^\"“”]*[\"”]\s*\(([^()]*)\)")
_MARKDOWN = re.compile(r"(^|\n)\s*(?:[*\-•]|#+|\d+\.)\s+")
_CLAUSE_SPLIT = re.compile(r"(?<=[.!?।॥;:,])\s+|\n+")
_NUMBER = re.compile(r"\d+")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'’\-]*")
_DIGIT_GROUP = re.compile(r"(?<=\d),(?=\d{2,3}\b)")
_RUPEES = re.compile(r"\b(?:Rs|INR)\.?\s*")
_LONE_DASH = re.compile(r"(?<!\w)-|-(?!\w)")
# Python's \w misses Indic vowel signs (matras), so the scripts' blocks are listed explicitly.
_NOT_SPEAKABLE = re.compile("[^\\w\\s'\\-\u0900-\u097f\u0c80-\u0cff]")

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_KANNADA_DIGITS = str.maketrans("೦೧೨೩೪೫೬೭೮೯", "0123456789")

# Digit names (hi/kn numbers are read digit by digit: correct, if not elegant).
_DIGITS: dict[Language, list[str]] = {
    "hi": ["शून्य", "एक", "दो", "तीन", "चार", "पाँच", "छह", "सात", "आठ", "नौ"],
    "kn": ["ಸೊನ್ನೆ", "ಒಂದು", "ಎರಡು", "ಮೂರು", "ನಾಲ್ಕು", "ಐದು", "ಆರು", "ಏಳು", "ಎಂಟು", "ಒಂಬತ್ತು"],
}

# fmt: off
_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
         "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
# fmt: on


def english_number(n: int) -> str:
    """0 ≤ n < 10**7 in words; larger numbers are read digit by digit."""
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else " " + _ONES[n % 10])
    if n < 1000:
        rest = n % 100
        return _ONES[n // 100] + " hundred" + ("" if rest == 0 else " " + english_number(rest))
    if n < 10**7:
        rest = n % 1000
        head = english_number(n // 1000) + " thousand"
        return head + ("" if rest == 0 else " " + english_number(rest))
    return " ".join(_ONES[int(d)] for d in str(n))


def _number_words(match: re.Match[str], language: Language) -> str:
    digits = match.group(0)
    if language == "en":
        n = int(digits)
        if len(digits) == 4 and 1100 <= n <= 2099 and not 2000 <= n <= 2009 and n % 100:
            return f" {english_number(n // 100)} {english_number(n % 100)} "  # 1955: years
        return f" {english_number(n)} "
    return " " + " ".join(_DIGITS[language][int(d)] for d in digits) + " "


def speech_clauses(text: str, language: Language) -> list[str]:
    """Clauses to synthesise one after another (with a short pause in between)."""
    text = _MARKERS.sub("", text)
    if language != "en":
        text = _QUOTE_WITH_TRANSLATION.sub(r"\1", text)
        text = text.translate(_DEVANAGARI_DIGITS).translate(_KANNADA_DIGITS)
    text = _MARKDOWN.sub(r"\1", text)
    text = text.replace("(", " ").replace(")", " ").replace('"', "").replace("“", "")
    text = text.replace("”", "").replace("/", " ")
    text = _DIGIT_GROUP.sub("", text)  # 1,00,000 / 4,000 → one number
    if language == "en":
        text = _RUPEES.sub("rupees ", text)
    text = _NUMBER.sub(lambda m: _number_words(m, language), text)
    clauses = []
    for clause in _CLAUSE_SPLIT.split(text):
        if language != "en":
            clause = _LATIN_WORD.sub(" ", clause)  # the hi/kn voices cannot read Latin script
        clause = _NOT_SPEAKABLE.sub(" ", clause.replace("।", " ").replace("॥", " "))
        clause = _LONE_DASH.sub(" ", clause)
        clause = re.sub(r"\s+", " ", clause).strip()
        if any(ch.isalpha() for ch in clause):
            clauses.append(clause)
    return clauses
