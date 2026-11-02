"""Translation providers: Hindi / Kannada question → English (for BM25 and query understanding).

Phase 5 uses the local LLM (ADR 0005). IndicTrans2 can implement the same protocol later.
"""

from typing import Protocol

import structlog

from app.nlp.glossary import terms_in
from app.nlp.language import LANGUAGE_NAMES, Language
from app.providers.llm import LLMProvider

logger = structlog.get_logger(__name__)

_SYSTEM = """\
You translate questions about Indian family law into English.
Output ONLY the English translation of the question: no notes, no answer, no quotation marks.
Keep names, numbers, section numbers and Act names exactly. Translate faithfully; do not add
or drop details."""


_ANSWER_SYSTEM = """\
You translate answers of an Indian family-law assistant from English into {target}.
Rules:
- Output ONLY the translation, in simple everyday {target}.
- Keep every citation marker such as [1] or [2][3] exactly as written, in the same place.
- Text inside double quotation marks is quoted law: copy it unchanged, in English.
- Keep names, numbers, dates, section numbers and Act names exactly.
- Do not add, drop or soften any statement."""


class TranslationProvider(Protocol):
    async def to_english(self, text: str, source: Language, romanized: bool = False) -> str: ...

    async def from_english(self, text: str, target: Language, romanized: bool = False) -> str: ...


class LLMTranslator:
    def __init__(self, llm: LLMProvider, light_llm: LLMProvider | None = None) -> None:
        self._llm = llm  # answers: long, must keep [n] markers and quotes
        self._light = light_llm or llm  # questions: short

    async def to_english(self, text: str, source: Language, romanized: bool = False) -> str:
        if source == "en":
            return text
        terms = terms_in(text, source)
        hints = "\n".join(f"- {' / '.join(t.forms(source))} = {t.en}" for t in terms)
        name = LANGUAGE_NAMES[source] + (" (written in Latin script)" if romanized else "")
        prompt = f"Translate this {name} question into English.\n"
        if hints:
            prompt += f"Use these legal term equivalents:\n{hints}\n"
        prompt += f"\nQuestion: {text}"
        english = await self._light.generate(_SYSTEM, prompt, temperature=0.0, max_tokens=256)
        english = english.strip().strip('"').strip()
        logger.info("query_translated", source=source, chars=len(text))
        return english or text

    async def from_english(self, text: str, target: Language, romanized: bool = False) -> str:
        """Translate an English answer, preserving [n] markers and quoted English text."""
        if target == "en":
            return text
        name = LANGUAGE_NAMES[target]
        if romanized:
            name += " written in Latin script (Hinglish)"
        terms = terms_in(text, "en")
        hints = "\n".join(f"- {t.en} = {' / '.join(t.forms(target))}" for t in terms)
        prompt = f"Use these legal terms:\n{hints}\n\n" if hints else ""
        prompt += f"English:\n{text}"
        translated = await self._llm.generate(
            _ANSWER_SYSTEM.format(target=name), prompt, temperature=0.0, max_tokens=1500
        )
        logger.info("answer_translated", target=target, chars=len(text))
        return translated.strip()
