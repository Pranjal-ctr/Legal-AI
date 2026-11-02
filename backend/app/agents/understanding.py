"""Query understanding: topic, applicability facts, scope, emergency, standalone English query.

The LLM extracts a ``QueryAnalysis`` as schema-constrained JSON; deterministic keyword rules
then confirm or fill the facts (rules only ever add explicitly stated facts, never guesses
from names). If the LLM call fails, the rules alone produce the analysis.
"""

import json
import re
from collections.abc import Sequence
from typing import Literal

import structlog
from pydantic import BaseModel, Field, ValidationError

from app.core.security import log_safe_error
from app.providers.llm import LLMError, LLMProvider

logger = structlog.get_logger(__name__)

Topic = Literal[
    "marriage",
    "divorce",
    "maintenance",
    "child_custody",
    "domestic_violence",
    "dowry",
    "adoption",
    "succession",
    "other_family_law",
    "out_of_scope",
]
Religion = Literal[
    "hindu", "sikh", "jain", "buddhist", "muslim", "christian", "parsi", "jewish", "other",
    "unknown",
]  # fmt: skip
MarriageType = Literal[
    "hindu_rites", "special_marriage_act", "muslim_nikah", "christian", "other", "unknown"
]


class UserFacts(BaseModel):
    """Facts the user stated explicitly (clarification answers, later the session profile)."""

    religion: Religion | Literal["unspecified"] | None = None  # "unspecified" = answer generally
    marriage_type: MarriageType | None = None


class QueryAnalysis(BaseModel):
    in_scope: bool = Field(description="About Indian family law or closely related rights.")
    topic: Topic
    religion: Religion = "unknown"
    marriage_type: MarriageType = "unknown"
    emergency: bool = Field(
        default=False, description="Immediate danger: violence now, threats to life, abduction."
    )
    standalone_question: str = Field(
        description="The question in English, self-contained (resolve 'it', 'that case', ...)."
    )
    legal_terms: list[str] = Field(
        default_factory=list,
        max_length=4,
        description="Statutory terms for the question, for search only (no section numbers).",
    )


_SYSTEM = """\
You analyse questions sent to an Indian family-law information assistant. Return JSON only.

Fields:
- in_scope: true if the question is about Indian family law (marriage, divorce, maintenance,
  custody, domestic violence, dowry, adoption, succession) or closely related rights; false
  for unrelated topics (company law, taxes, recipes, ...).
- topic: the main topic.
- religion: ONLY if the user states it or it is unmistakable from the words used (e.g.
  "Hindu marriage", "saptapadi" → hindu; "nikah", "talaq-e-biddat", "mehr" → muslim;
  "church wedding" → christian). Never infer religion from a person's name. Otherwise "unknown".
- marriage_type: "special_marriage_act" for civil/court/registered inter-faith marriages under
  that Act; "hindu_rites" for Hindu ceremonies; otherwise as stated, or "unknown".
- emergency: true only for immediate danger (ongoing violence, threats to life, a child being
  taken away right now).
- standalone_question: the user's question rewritten in clear English so it makes sense on its
  own, using the conversation for context. Keep every fact the user gave; add nothing.
- legal_terms: up to 3 short phrases naming the legal concepts in the vocabulary Indian statutes
  use, to help search (e.g. "maintenance while the case is pending" → "maintenance pendente
  lite"; "husband left and won't return" → "restitution of conjugal rights", "desertion").
  No section numbers, no case names. Empty list if the question already uses legal terms."""

# Explicit statements only (English + common Hindi/Kannada words); never names.
_RELIGION_RULES: list[tuple[Religion, re.Pattern[str]]] = [
    (
        "muslim",
        re.compile(
            r"\b(muslim|islam\w*|nikah|nikaah|mehr|talaq-e|shariat|shariah)\b|मुस्लिम|निकाह|ಮುಸ್ಲಿಂ",
            re.I,
        ),
    ),
    ("christian", re.compile(r"\b(christian|church wedding)\b|ईसाई|ಕ್ರಿಶ್ಚಿಯನ್", re.I)),
    ("parsi", re.compile(r"\b(parsi|zoroastrian)\b|पारसी|ಪಾರ್ಸಿ", re.I)),
    ("jewish", re.compile(r"\b(jewish|jew)\b|यहूदी", re.I)),
    ("sikh", re.compile(r"\b(sikh|anand karaj)\b|सिख|ಸಿಖ್", re.I)),
    ("jain", re.compile(r"\b(jain|jaina)\b|जैन|ಜೈನ", re.I)),
    ("buddhist", re.compile(r"\b(buddhist)\b|बौद्ध|ಬೌದ್ಧ", re.I)),
    ("hindu", re.compile(r"\b(hindu|saptapadi|hma)\b|हिंदू|हिन्दू|सप्तपदी|ಹಿಂದೂ|ಸಪ್ತಪದಿ", re.I)),
]
_SMA_RULE = re.compile(r"special marriage act|\bSMA\b|विशेष विवाह|ವಿಶೇಷ ವಿವಾಹ", re.I)


def rule_facts(texts: Sequence[str]) -> tuple[Religion, MarriageType]:
    """Religion / marriage type explicitly named in any of ``texts`` (else "unknown")."""
    joined = "\n".join(texts)
    religion: Religion = "unknown"
    found = [name for name, pattern in _RELIGION_RULES if pattern.search(joined)]
    if len(found) == 1:  # several religions named (e.g. inter-faith): leave it to the LLM
        religion = found[0]
    marriage: MarriageType = "special_marriage_act" if _SMA_RULE.search(joined) else "unknown"
    return religion, marriage


def apply_rules(analysis: QueryAnalysis, texts: Sequence[str]) -> QueryAnalysis:
    religion, marriage = rule_facts(texts)
    update: dict[str, str] = {}
    if religion != "unknown" and analysis.religion in ("unknown", "other"):
        update["religion"] = religion
    if marriage != "unknown":
        update["marriage_type"] = marriage
    return analysis.model_copy(update=update) if update else analysis


def fallback_analysis(question_en: str, texts: Sequence[str]) -> QueryAnalysis:
    """Rules-only analysis used when the LLM is unavailable or returns invalid JSON."""
    religion, marriage = rule_facts(texts)
    return QueryAnalysis(
        in_scope=True,  # never refuse on a guess
        topic="other_family_law",
        religion=religion,
        marriage_type=marriage,
        emergency=False,
        standalone_question=question_en,
    )


class QueryUnderstanding:
    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def analyse(
        self,
        question: str,
        question_en: str,
        history: Sequence[tuple[str, str]] = (),
    ) -> QueryAnalysis:
        """``history`` = earlier (role, text) turns, oldest first (Phase 8 memory)."""
        texts = [question, question_en]
        convo = "\n".join(f"{role}: {text}" for role, text in history[-6:])
        prompt = (f"Conversation so far:\n{convo}\n\n" if convo else "") + (
            f"User question: {question}\n"
            + (f"English translation: {question_en}\n" if question_en != question else "")
        )
        try:
            raw = await self._llm.generate(
                _SYSTEM,
                prompt,
                temperature=0.0,
                json_schema=QueryAnalysis.model_json_schema(),
                max_tokens=400,
            )
            analysis = QueryAnalysis.model_validate(json.loads(raw))
        except (LLMError, ValueError, ValidationError) as exc:
            logger.warning("understanding_fallback", **log_safe_error(exc))
            return fallback_analysis(question_en, texts)
        if not analysis.standalone_question.strip():
            analysis = analysis.model_copy(update={"standalone_question": question_en})
        return apply_rules(analysis, texts)
