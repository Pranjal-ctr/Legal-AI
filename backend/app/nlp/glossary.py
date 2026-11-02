"""Legal terminology glossary (en ↔ hi/kn) used to keep translations and answers consistent."""

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from app.nlp.language import Language

_GLOSSARY_FILE = Path(__file__).with_name("legal_glossary.json")


@dataclass(frozen=True)
class GlossaryTerm:
    en: str
    hi: tuple[str, ...]
    kn: tuple[str, ...]

    def forms(self, language: Language) -> tuple[str, ...]:
        return (self.en,) if language == "en" else getattr(self, language)


@cache
def load_glossary() -> tuple[GlossaryTerm, ...]:
    data = json.loads(_GLOSSARY_FILE.read_text(encoding="utf-8"))
    return tuple(
        GlossaryTerm(en=t["en"], hi=tuple(t["hi"]), kn=tuple(t["kn"])) for t in data["terms"]
    )


def terms_in(text: str, language: Language) -> list[GlossaryTerm]:
    """Glossary entries whose ``language`` form occurs in ``text`` (case-insensitive)."""
    lowered = text.lower()
    return [t for t in load_glossary() if any(f.lower() in lowered for f in t.forms(language))]


def glossary_lines(terms: list[GlossaryTerm], target: Language) -> str:
    """``english = target form`` lines for a prompt (empty when nothing matches)."""
    if target == "en":
        return ""
    return "\n".join(f"- {t.en} = {' / '.join(t.forms(target))}" for t in terms)
