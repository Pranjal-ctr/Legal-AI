"""Deterministic language detection for English / Hindi / Kannada (incl. romanized Hindi).

Script counting is exact for Devanagari and Kannada. Latin-script text is English unless it
carries several common Hindi function words ("kya", "hai", "mera", ...), i.e. romanized Hindi.
"""

import re
from dataclasses import dataclass
from typing import Literal

Language = Literal["en", "hi", "kn"]
LANGUAGE_NAMES: dict[Language, str] = {"en": "English", "hi": "Hindi", "kn": "Kannada"}

_DEVANAGARI = re.compile(f"[{chr(0x0900)}-{chr(0x097F)}]")
_KANNADA = re.compile(f"[{chr(0x0C80)}-{chr(0x0CFF)}]")
_LATIN = re.compile(r"[A-Za-z]")
_WORD = re.compile(r"[a-z]+")

# Frequent Hindi words in Latin script that are not (common) English words.
# fmt: off
_HINGLISH = frozenset((
    "kya", "hai", "hain", "tha", "thi", "mera", "meri", "mere", "mujhe", "mujhko", "hum",
    "hamara", "humara", "aap", "aapka", "apna", "apni", "pati", "patni", "talaq", "talak",
    "shaadi", "shadi", "vivah", "kaise", "kitne", "kitna", "kitni", "kab", "kahan", "kyun",
    "nahi", "nahin", "aur", "ke", "ki", "ko", "se", "mein", "liye", "kar", "karna", "karke",
    "sakta", "sakti", "sakte", "milega", "milegi", "chahiye", "wala", "wali", "hota", "hoti",
    "hote", "bachche", "bacche", "baccha", "ghar", "agar", "toh", "bhi", "gaya", "gayi", "raha",
    "rahi", "saal", "din", "paisa", "kharcha", "dahej", "sasural", "maike", "adalat", "kanoon",
    "kanun",
))
# fmt: on


@dataclass(frozen=True)
class DetectedLanguage:
    language: Language
    romanized: bool = False  # Hindi written in Latin script ("Hinglish")


def detect_language(text: str) -> DetectedLanguage:
    deva = len(_DEVANAGARI.findall(text))
    kann = len(_KANNADA.findall(text))
    latin = len(_LATIN.findall(text))
    if kann and kann >= max(deva, latin * 0.5):
        return DetectedLanguage("kn")
    if deva and deva >= latin * 0.5:
        return DetectedLanguage("hi")
    words = _WORD.findall(text.lower())
    markers = {w for w in words if w in _HINGLISH}
    if len(markers) >= 2 and sum(w in _HINGLISH for w in words) >= 0.25 * len(words):
        return DetectedLanguage("hi", romanized=True)
    return DetectedLanguage("en")


def answer_language_instruction(language: Language, romanized: bool = False) -> str:
    """How the generator should write its answer (sources and quotations stay English)."""
    if language == "en":
        return "Write the answer in English."
    if language == "hi" and romanized:
        target = "Hindi using Latin script (Hinglish, as the user wrote)"
    else:
        script = "Devanagari" if language == "hi" else "Kannada"
        target = f"{LANGUAGE_NAMES[language]} ({script} script)"
    return (
        f"Write the answer in {target}, in simple words. Do NOT translate quotations: any "
        "words inside quotation marks must be copied exactly from the English sources; "
        f"explain them in {LANGUAGE_NAMES[language]} after the quotation."
    )
