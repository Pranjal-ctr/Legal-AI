"""Deterministic agentic orchestrator (Phases 6-7, ADR 0006).

An explicit state machine; LLM calls only where they earn their place:

  LANGUAGE → UNDERSTAND → (OUT_OF_SCOPE | CLARIFY) → GATE → RETRIEVE (round 1)
  → ASSESS evidence → [RETRIEVE round 2 with a follow-up query] → GENERATE (English)
  → VALIDATE citations + quotations [regenerate once if uncited] → TRANSLATE → RESPOND

Answers are generated and verified in English (the language of the canonical law) and then
translated for the user, so every citation and quotation is checked against the sources.
"""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ValidationError

from app.agents.applicability import (
    CLARIFY_OPTIONS,
    CLARIFY_QUESTION,
    EMERGENCY_NOTICE,
    GENERATOR_NOT_APPLICABLE,
    GENERATOR_UNSPECIFIED,
    NOT_APPLICABLE_NOTICE,
    OUT_OF_SCOPE_ANSWER,
    UNSPECIFIED_NOTICE,
    Applicability,
    assess,
    fill_facts,
    merge_facts,
)
from app.agents.understanding import QueryAnalysis, QueryUnderstanding, UserFacts
from app.agents.validation import check_quotes, markers_preserved, restore_quotes
from app.core.security import log_safe_error
from app.nlp.language import LANGUAGE_NAMES, Language, detect_language
from app.providers.llm import LLMError, LLMProvider
from app.providers.translation import TranslationProvider
from app.rag.prompt import (
    EvidenceItem,
    assemble_evidence,
    build_prompt,
    build_system_prompt,
    check_citations,
    source_heading,
)
from app.retrieval.index import RetrievedChunk, Retriever

logger = structlog.get_logger(__name__)

ResultKind = Literal["answer", "clarification", "out_of_scope"]

NO_EVIDENCE_ANSWER = (
    "I could not find any source in the current corpus that addresses this question, "
    "so I cannot answer it."
)
UNCITED_RETRY_NOTE = (
    "Your previous answer cited no sources. Answer again and support each statement with "
    "[n] source numbers, or say clearly that the sources do not answer the question."
)
TRANSLATION_FAILED_NOTICE: dict[Language, str] = {
    "en": "",
    "hi": "अनुवाद की जाँच विफल रही, इसलिए उत्तर अंग्रेज़ी में दिखाया गया है।",
    "kn": "ಅನುವಾದದ ಪರಿಶೀಲನೆ ವಿಫಲವಾಯಿತು, ಆದ್ದರಿಂದ ಉತ್ತರವನ್ನು ಇಂಗ್ಲಿಷ್‌ನಲ್ಲಿ ತೋರಿಸಲಾಗಿದೆ.",
}


@dataclass(frozen=True)
class TraceStep:
    step: str
    ms: int
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClarifyOption:
    field: str  # "religion" | "marriage_type"
    value: str
    label: str


@dataclass(frozen=True)
class Clarification:
    question: str
    options: list[ClarifyOption]


@dataclass(frozen=True)
class Validation:
    invalid_citations: list[int] = field(default_factory=list)
    verified_quotes: int = 0
    unquoted: list[str] = field(default_factory=list)  # non-verbatim "quotes" that were unquoted
    regenerated: bool = False
    translation_ok: bool = True


@dataclass(frozen=True)
class ChatResult:
    kind: ResultKind
    answer: str  # in the user's language
    answer_en: str  # the verified English answer
    language: Language
    romanized: bool
    english_query: str  # standalone English question used for search
    evidence: list[EvidenceItem]
    cited: list[int]
    notices: list[str]
    emergency: bool
    model: str
    rounds: int
    validation: Validation
    trace: list[TraceStep]
    analysis: QueryAnalysis | None = None
    applicability: Applicability | None = None
    clarification: Clarification | None = None

    @property
    def grounded(self) -> bool:
        return bool(self.cited)


class EvidenceAssessment(BaseModel):
    relevant: list[int]
    sufficient: bool
    followup_query: str = ""


_ASSESS_SYSTEM = """\
You check whether retrieved sources can answer a question about Indian family law. Return JSON.
- relevant: numbers of the sources that help answer the question.
- sufficient: true if the relevant sources together answer the question.
- followup_query: if not sufficient, ONE short English search query for what is missing
  (for example the statute section or legal concept), else ""."""


StepCallback = Callable[[str], Awaitable[None]]


class _Timer:
    """Times each step; ``on_step`` is told when a step starts (live progress for the UI)."""

    def __init__(self, on_step: StepCallback | None = None) -> None:
        self.trace: list[TraceStep] = []
        self._on_step = on_step

    async def run(self, step: str, coro: Any) -> Any:
        if self._on_step is not None:
            try:
                await self._on_step(step)
            except Exception:  # progress reporting must never break answering
                logger.warning("step_callback_failed", step=step)
        started = time.perf_counter()
        result = await coro
        self.trace.append(TraceStep(step, int((time.perf_counter() - started) * 1000)))
        return result

    def note(self, **detail: Any) -> None:
        last = self.trace[-1]
        self.trace[-1] = TraceStep(last.step, last.ms, {**last.detail, **detail})


class Orchestrator:
    def __init__(
        self,
        retriever: Retriever,
        llm: LLMProvider,
        translator: TranslationProvider,
        *,
        top_k: int = 6,
        max_rounds: int = 2,
        assess_evidence: bool = True,
        max_sources: int = 8,
        light_llm: LLMProvider | None = None,
        warmup_llm: bool = True,
    ) -> None:
        self.retriever = retriever
        self.llm = llm
        # Short structured calls (understanding, evidence check) may use a cheaper model.
        self.light_llm = light_llm or llm
        self.translator = translator
        self.understanding = QueryUnderstanding(self.light_llm)
        self.warmup_llm = warmup_llm
        self.top_k = top_k
        self.max_rounds = max(1, min(max_rounds, 2))
        self.assess_evidence = assess_evidence
        self.max_sources = max_sources

    # ---- steps --------------------------------------------------------------------------

    async def _search(
        self, question: str, english: str, legal_terms: Sequence[str] = ()
    ) -> list[RetrievedChunk]:
        """Search with the user's words, the English question and (if any) statutory terms.

        Lay phrasing ("maintenance while my case is pending") shares no words with the statute
        ("maintenance pendente lite"), so the terms join both the first stage and the reranker
        query; they only steer search, the answer is still grounded in what is retrieved.
        """
        terms = "; ".join(t.strip() for t in legal_terms if t.strip())
        alt = [q for q in (english, terms) if q and q != question]
        rerank = english or question
        if terms:
            rerank = f"{rerank} ({terms})"
        return await asyncio.to_thread(
            self.retriever.search, question, self.top_k, alt_queries=alt, rerank_query=rerank
        )

    def _filter(self, evidence: list[EvidenceItem], gate: Applicability) -> list[EvidenceItem]:
        """Withhold statutes of a personal law that does not apply to the user."""
        if gate.decision != "not_applicable":
            return evidence
        return [
            e
            for e in evidence
            if not (e.document.doc_type == "statute" and e.document.personal_law == "hindu")
        ]

    async def _assess(self, question_en: str, evidence: list[EvidenceItem]) -> EvidenceAssessment:
        listing = "\n\n".join(f"[{e.n}] {source_heading(e)}\n{e.unit.text[:700]}" for e in evidence)
        prompt = f"QUESTION: {question_en}\n\nSOURCES:\n\n{listing}"
        try:
            raw = await self.light_llm.generate(
                _ASSESS_SYSTEM,
                prompt,
                temperature=0.0,
                json_schema=EvidenceAssessment.model_json_schema(),
                max_tokens=200,
            )
            result = EvidenceAssessment.model_validate(json.loads(raw))
        except (LLMError, ValueError, ValidationError) as exc:
            logger.warning("assessment_failed", **log_safe_error(exc))
            return EvidenceAssessment(relevant=[e.n for e in evidence], sufficient=True)
        valid = {e.n for e in evidence}
        return result.model_copy(update={"relevant": [n for n in result.relevant if n in valid]})

    @staticmethod
    def _renumber(items: Sequence[EvidenceItem]) -> list[EvidenceItem]:
        return [
            EvidenceItem(
                n=i,
                unit=e.unit,
                document=e.document,
                score=e.score,
                matched_chunk_ids=e.matched_chunk_ids,
            )
            for i, e in enumerate(items, start=1)
        ]

    async def _generate(
        self, question: str, question_en: str, evidence: list[EvidenceItem], gate: Applicability
    ) -> tuple[str, list[int], Validation]:
        system = build_system_prompt("en")
        if gate.decision == "not_applicable":
            system += "\n" + GENERATOR_NOT_APPLICABLE + "\n"
        elif gate.decision == "unknown":
            system += "\n" + GENERATOR_UNSPECIFIED + "\n"
        prompt = build_prompt(question_en, evidence)
        if question != question_en:
            prompt += f"\n(The user originally asked: {question})"
        sources = [e.unit.text for e in evidence]

        raw = await self.llm.generate(system, prompt)
        check = check_citations(raw, len(evidence))
        regenerated = False
        if not check.cited:  # one retry with an explicit reminder
            regenerated = True
            raw = await self.llm.generate(system, prompt + "\n\n" + UNCITED_RETRY_NOTE)
            check = check_citations(raw, len(evidence))
        quotes = check_quotes(check.answer, sources)
        return (
            quotes.answer,
            check.cited,
            Validation(
                invalid_citations=check.invalid,
                verified_quotes=len(quotes.verified),
                unquoted=quotes.unquoted,
                regenerated=regenerated,
            ),
        )

    async def _translate(
        self, answer_en: str, language: Language, romanized: bool, sources: list[str]
    ) -> tuple[str, bool]:
        """Translate the verified answer; fall back to English if [n] markers are lost.

        Quotations the translator translated are restored to the exact English law text.
        """
        if language == "en":
            return answer_en, True
        for _attempt in range(2):
            translated = await self.translator.from_english(answer_en, language, romanized)
            if translated and markers_preserved(answer_en, translated):
                return restore_quotes(translated, answer_en, sources), True
            logger.warning("translation_markers_lost", language=language)
        return answer_en, False

    # ---- state machine ------------------------------------------------------------------

    async def answer(
        self,
        question: str,
        language: Language | None = None,
        facts: UserFacts | None = None,
        history: Sequence[tuple[str, str]] = (),
        profile: UserFacts | None = None,
        on_step: StepCallback | None = None,
    ) -> ChatResult:
        """``facts``: stated for this question (clarification answer). ``history``: earlier
        (role, English text) turns. ``profile``: the session's earlier answers; they only fill
        facts the current question leaves unknown. ``on_step``: awaited as each step starts."""
        timer = _Timer(on_step)
        detected = detect_language(question)
        lang: Language = language or detected.language
        romanized = detected.romanized and lang == "hi"

        # LANGUAGE: English version of the question (also used by understanding).
        question_en = question
        if detected.language != "en":
            question_en = await timer.run(
                "translate_query",
                self.translator.to_english(question, detected.language, detected.romanized),
            )

        # UNDERSTAND
        analysis: QueryAnalysis = await timer.run(
            "understand", self.understanding.analyse(question, question_en, history)
        )
        timer.note(topic=analysis.topic, religion=analysis.religion, in_scope=analysis.in_scope)
        english = analysis.standalone_question or question_en
        notices: list[str] = []
        if analysis.emergency:
            notices.append(EMERGENCY_NOTICE[lang])

        def result(kind: ResultKind, answer_en: str, **kw: Any) -> ChatResult:
            return ChatResult(
                kind=kind,
                answer=kw.pop("answer", answer_en),
                answer_en=answer_en,
                language=lang,
                romanized=romanized,
                english_query=english,
                evidence=kw.pop("evidence", []),
                cited=kw.pop("cited", []),
                notices=notices,
                emergency=analysis.emergency,
                model=self.llm.model_name,
                rounds=kw.pop("rounds", 0),
                validation=kw.pop("validation", Validation()),
                trace=timer.trace,
                analysis=analysis,
                **kw,
            )

        # OUT OF SCOPE (the topic label is unreliable for unrelated questions; trust in_scope)
        if not analysis.in_scope and not analysis.emergency:
            return result(
                "out_of_scope", OUT_OF_SCOPE_ANSWER["en"], answer=OUT_OF_SCOPE_ANSWER[lang]
            )

        # GATE → CLARIFY (user-stated facts override extracted ones)
        facts = fill_facts(analysis, facts, profile)
        analysis = merge_facts(analysis, facts)
        gate = assess(analysis, facts)
        if gate.ask_user:
            clarification = Clarification(
                question=CLARIFY_QUESTION[lang],
                options=[ClarifyOption(f, v, labels[lang]) for f, v, labels in CLARIFY_OPTIONS],
            )
            return result(
                "clarification",
                CLARIFY_QUESTION["en"],
                answer=clarification.question,
                applicability=gate,
                clarification=clarification,
            )
        if gate.decision == "not_applicable":
            notices.append(NOT_APPLICABLE_NOTICE[lang])
        elif gate.decision == "unknown":
            notices.append(UNSPECIFIED_NOTICE[lang])

        # RETRIEVE round 1
        hits = await timer.run(
            "retrieve_1", self._search(question, english, analysis.legal_terms[:3])
        )
        evidence = self._filter(assemble_evidence(self.retriever.corpus, hits), gate)
        timer.note(sources=[e.unit.chunk_id for e in evidence])
        rounds = 1

        # ASSESS → RETRIEVE round 2
        if self.assess_evidence and evidence:
            verdict: EvidenceAssessment = await timer.run("assess", self._assess(english, evidence))
            timer.note(
                relevant=verdict.relevant,
                sufficient=verdict.sufficient,
                followup=verdict.followup_query,
            )
            kept = [e for e in evidence if e.n in verdict.relevant] or evidence
            if not verdict.sufficient and verdict.followup_query and self.max_rounds > 1:
                more = await timer.run("retrieve_2", self._search(verdict.followup_query, ""))
                rounds = 2
                seen = {e.unit.chunk_id for e in kept}
                extra = [
                    e
                    for e in self._filter(assemble_evidence(self.retriever.corpus, more), gate)
                    if e.unit.chunk_id not in seen
                ]
                timer.note(added=[e.unit.chunk_id for e in extra])
                kept = kept + extra
            evidence = self._renumber(kept[: self.max_sources])

        if not evidence:
            message = NO_EVIDENCE_ANSWER
            translated, _ = await self._translate(message, lang, romanized, [])
            return result("answer", message, answer=translated, rounds=rounds, applicability=gate)

        # GENERATE + VALIDATE (English)
        answer_en, cited, validation = await timer.run(
            "generate", self._generate(question, english, evidence, gate)
        )
        timer.note(
            cited=cited,
            invalid=validation.invalid_citations,
            unquoted=len(validation.unquoted),
            regenerated=validation.regenerated,
        )

        # TRANSLATE
        answer = answer_en
        if lang != "en":
            answer, ok = await timer.run(
                "translate_answer",
                self._translate(answer_en, lang, romanized, [e.unit.text for e in evidence]),
            )
            validation = Validation(**{**validation.__dict__, "translation_ok": ok})
            if not ok:
                notices.append(TRANSLATION_FAILED_NOTICE[lang])

        logger.info(
            "chat_answered",
            language=lang,
            topic=analysis.topic,
            gate=gate.decision,
            rounds=rounds,
            cited=cited,
            steps=[(s.step, s.ms) for s in timer.trace],
        )
        return result(
            "answer",
            answer_en,
            answer=answer,
            evidence=evidence,
            cited=cited,
            rounds=rounds,
            validation=validation,
            applicability=gate,
        )

    async def warmup(self) -> None:
        """Load the embedding/reranker weights and the LLM so the first user waits less."""
        started = time.perf_counter()
        try:
            await asyncio.to_thread(self.retriever.search, "divorce on the ground of cruelty", 1)
            if self.warmup_llm:
                await self.llm.generate("Reply with OK.", "OK", temperature=0.0, max_tokens=2)
        except Exception as exc:  # warm-up is an optimisation; requests still work without it
            logger.warning("warmup_failed", error=str(exc)[:200])
            return
        logger.info("warmup_done", ms=int((time.perf_counter() - started) * 1000))

    def close(self) -> None:
        self.retriever.close()


__all__ = ["LANGUAGE_NAMES", "ChatResult", "Orchestrator"]
