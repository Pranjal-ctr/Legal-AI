import asyncio

from app.agents.understanding import UserFacts
from app.agents.validation import check_quotes, markers_preserved, restore_quotes
from tests.fakes import FakeLLM, make_orchestrator, scripted_llm


def _run(llm: FakeLLM, question: str, **kw: object):  # type: ignore[no-untyped-def]
    return asyncio.run(make_orchestrator(llm).answer(question, **kw))  # type: ignore[arg-type]


def _systems(llm: FakeLLM) -> list[str]:
    return [system.split("\n", 1)[0][:30] for system, _ in llm.calls]


# ---- validators ----------------------------------------------------------------------------


def test_verbatim_quotes_kept_paraphrased_quotes_unquoted() -> None:
    sources = ["2. Grounds.— (1) alpha grounds apply. (2) beta waiting period."]
    answer = (
        'The Act says "alpha grounds apply" [1]. It also says "gamma rules always win" [1]. '
        "A 'word' and “Beta  Waiting period.” stay."
    )

    check = check_quotes(answer, sources)

    assert check.verified == ["alpha grounds apply", "Beta  Waiting period."]
    assert check.unquoted == ["gamma rules always win"]
    assert "says gamma rules always win [1]" in check.answer
    assert '"alpha grounds apply"' in check.answer


def test_single_quoted_word_is_emphasis_not_a_quotation() -> None:
    check = check_quotes('The term "cruelty" is used [1].', ["no match here"])

    assert check.unquoted == []
    assert check.answer == 'The term "cruelty" is used [1].'


def test_markers_preserved() -> None:
    assert markers_preserved("A [1]. B [2][1].", "अ [1]। ब [2][1]।")
    assert not markers_preserved("A [1]. B [2].", "अ [1]। ब।")
    assert not markers_preserved("A [1].", "अ [1][1]।")


# ---- state machine -------------------------------------------------------------------------


def test_english_answer_path() -> None:
    llm = scripted_llm(answer='Alpha grounds apply [1]. "invented quote here" [1].')

    result = _run(llm, "what alpha grounds apply")

    assert result.kind == "answer"
    assert result.cited == [1]
    assert result.validation.unquoted == ["invented quote here"]
    assert result.answer == "Alpha grounds apply [1]. invented quote here [1]."
    assert result.rounds == 1
    assert [s.step for s in result.trace] == ["understand", "retrieve_1", "assess", "generate"]
    assert _systems(llm)[0].startswith("You analyse questions")


def test_clarification_when_religion_unknown_for_personal_law_topic() -> None:
    llm = scripted_llm(analysis={"religion": "unknown"})

    result = _run(llm, "alpha grounds?", language="kn")

    assert result.kind == "clarification"
    assert result.clarification is not None
    assert result.answer == result.clarification.question
    assert "ಧರ್ಮ" in result.clarification.question  # Kannada text
    assert result.evidence == []
    assert len(llm.calls) == 1  # only understanding ran


def test_unspecified_religion_answers_with_notice() -> None:
    llm = scripted_llm(analysis={"religion": "unknown"})

    result = _run(llm, "alpha grounds?", facts=UserFacts(religion="unspecified"))

    assert result.kind == "answer"
    assert any("Hindus, Buddhists" in n for n in result.notices)
    assert "religion is not known" in llm.calls[-1][0]  # generator told to qualify


def test_not_applicable_withholds_the_statute() -> None:
    llm = scripted_llm(
        analysis={"religion": "muslim", "topic": "child_custody"},
        answer="Delta custody goes to mother [1].",
    )

    result = _run(llm, "alpha grounds and delta custody")

    assert all(e.document.doc_type != "statute" for e in result.evidence)
    assert any("may not govern your marriage" in n for n in result.notices)
    assert "NOT governed by the Hindu Marriage Act" in llm.calls[-1][0]


def test_secular_topic_is_not_gated() -> None:
    llm = scripted_llm(analysis={"religion": "unknown", "topic": "domestic_violence"})

    result = _run(llm, "delta custody")

    assert result.kind == "answer"
    assert result.applicability is not None
    assert result.applicability.decision == "not_gated"


def test_out_of_scope_skips_retrieval() -> None:
    llm = scripted_llm(analysis={"in_scope": False, "topic": "out_of_scope"})

    result = _run(llm, "how do I register a company?", language="hi")

    assert result.kind == "out_of_scope"
    assert result.answer.startswith("मैं केवल")
    assert result.rounds == 0
    assert len(llm.calls) == 1


def test_emergency_notice_comes_first() -> None:
    llm = scripted_llm(analysis={"emergency": True, "topic": "domestic_violence"})

    result = _run(llm, "delta custody right now")

    assert "112" in result.notices[0]
    assert result.emergency


def test_insufficient_evidence_triggers_second_round() -> None:
    llm = scripted_llm(
        assessment={"relevant": [1], "sufficient": False, "followup_query": "gamma registration"},
        answer="Gamma registration of records [2].",
    )

    result = _run(llm, "beta waiting period")

    assert result.rounds == 2
    assert "retrieve_2" in [s.step for s in result.trace]
    assert "act1:s3" in [e.unit.chunk_id for e in result.evidence]
    assert [e.n for e in result.evidence] == list(range(1, len(result.evidence) + 1))


def test_assessment_drops_irrelevant_sources() -> None:
    llm = scripted_llm(assessment={"relevant": [1], "sufficient": True})

    result = _run(llm, "beta waiting period")

    assert len(result.evidence) == 1
    assert result.rounds == 1


def test_uncited_answer_is_regenerated_once() -> None:
    replies = iter(["No citations here.", "Alpha grounds apply [1]."])
    base = scripted_llm()

    def responder(system: str, prompt: str) -> str:
        if system.startswith("You are Kanoon AI"):
            return next(replies)
        assert base.responder is not None
        return base.responder(system, prompt)

    result = _run(FakeLLM(responder=responder), "what alpha grounds apply")

    assert result.validation.regenerated
    assert result.cited == [1]


def test_hindi_question_is_answered_in_english_then_translated() -> None:
    llm = scripted_llm(query_en="what alpha grounds apply", translated_answer="अल्फा [1]।")

    result = _run(llm, "अल्फा आधार क्या हैं?")

    assert result.language == "hi"
    assert result.answer_en == "Alpha grounds apply [1]."
    assert result.answer == "अल्फा [1]।"
    assert result.validation.translation_ok
    steps = [s.step for s in result.trace]
    assert steps[0] == "translate_query"
    assert steps[-1] == "translate_answer"
    generator_system = next(s for s, _ in llm.calls if s.startswith("You are Kanoon AI"))
    assert "Write the answer in English." in generator_system


def test_translation_that_loses_markers_falls_back_to_english() -> None:
    llm = scripted_llm(query_en="what alpha grounds apply", translated_answer="अल्फा।")

    result = _run(llm, "अल्फा आधार क्या हैं?")

    assert result.answer == result.answer_en
    assert not result.validation.translation_ok
    assert any("अंग्रेज़ी" in n for n in result.notices)
    translations = [s for s, _ in llm.calls if s.startswith("You translate answers")]
    assert len(translations) == 2  # one retry


def test_quote_with_ellipsis_checks_each_fragment() -> None:
    sources = ["(1) Any marriage may, on a petition, be dissolved by a decree of divorce."]

    ok = check_quotes('It "may... be dissolved by a decree" [1].', sources)
    bad = check_quotes('It "may... be annulled at once" [1].', sources)

    assert ok.verified == ["may... be dissolved by a decree"]
    assert bad.unquoted == ["may... be annulled at once"]


def test_restore_quotes_puts_english_law_text_back() -> None:
    sources = ["the court may pass interim orders for custody of minor children"]
    english = 'The court "may pass interim orders" [1].'
    translated = 'ನ್ಯಾಯಾಲಯ "ಮಧ್ಯಂತರ ಆದೇಶಗಳನ್ನು ನೀಡಬಹುದು" [1].'

    restored = restore_quotes(translated, english, sources)

    assert restored == 'ನ್ಯಾಯಾಲಯ "may pass interim orders" (ಮಧ್ಯಂತರ ಆದೇಶಗಳನ್ನು ನೀಡಬಹುದು) [1].'


def test_restore_quotes_unquotes_when_quotes_cannot_be_paired() -> None:
    sources = ["the court may pass interim orders"]
    restored = restore_quotes(
        'अदालत "आदेश दे सकती है" और "कुछ और भी"', 'The court "may pass" [1].', sources
    )

    assert restored == "अदालत आदेश दे सकती है और कुछ और भी"


def test_out_of_scope_trusts_in_scope_even_with_a_family_topic_label() -> None:
    llm = scripted_llm(analysis={"in_scope": False, "topic": "succession"})

    assert _run(llm, "register a company?").kind == "out_of_scope"


def test_user_facts_are_reflected_in_the_analysis() -> None:
    llm = scripted_llm(analysis={"religion": "unknown"})

    result = _run(llm, "alpha grounds?", facts=UserFacts(religion="sikh"))

    assert result.analysis is not None
    assert result.analysis.religion == "sikh"


# ---- memory (Phase 8) -----------------------------------------------------------------------


def test_profile_fills_unknown_religion_so_no_clarification() -> None:
    llm = scripted_llm(analysis={"religion": "unknown"})

    result = _run(llm, "alpha grounds?", profile=UserFacts(religion="hindu"))

    assert result.kind == "answer"
    assert result.applicability is not None
    assert result.applicability.decision == "applies"


def test_question_statement_overrides_the_profile() -> None:
    llm = scripted_llm(analysis={"religion": "muslim"})

    result = _run(llm, "alpha grounds?", profile=UserFacts(religion="hindu"))

    assert result.applicability is not None
    assert result.applicability.decision == "not_applicable"


def test_request_facts_override_question_and_profile() -> None:
    llm = scripted_llm(analysis={"religion": "muslim"})

    result = _run(
        llm,
        "alpha grounds?",
        facts=UserFacts(religion="sikh"),
        profile=UserFacts(religion="christian"),
    )

    assert result.applicability is not None
    assert result.applicability.religion == "sikh"


def test_profile_unspecified_answers_generally() -> None:
    llm = scripted_llm(analysis={"religion": "unknown"})

    result = _run(llm, "alpha grounds?", profile=UserFacts(religion="unspecified"))

    assert result.kind == "answer"
    assert any("Hindus, Buddhists" in n for n in result.notices)


def test_history_reaches_the_understanding_prompt() -> None:
    llm = scripted_llm()

    _run(
        llm,
        "and the waiting period?",
        history=[("user", "alpha grounds?"), ("assistant", "A [1].")],
    )

    understanding_prompt = llm.calls[0][1]
    assert "Conversation so far:" in understanding_prompt
    assert "user: alpha grounds?" in understanding_prompt


# ---- latency (live progress + warm-up) --------------------------------------------------------


def test_on_step_reports_each_step_as_it_starts() -> None:
    steps: list[str] = []

    async def on_step(step: str) -> None:
        steps.append(step)

    llm = scripted_llm(query_en="what alpha grounds apply", translated_answer="अल्फा [1]।")
    result = _run(llm, "अल्फा आधार क्या हैं?", on_step=on_step)

    assert steps == [s.step for s in result.trace]


def test_failing_step_callback_does_not_break_answering() -> None:
    async def on_step(step: str) -> None:
        raise RuntimeError("client gone")

    result = _run(scripted_llm(), "what alpha grounds apply", on_step=on_step)

    assert result.kind == "answer"


def test_warmup_touches_retriever_and_llm_and_never_raises() -> None:
    llm = scripted_llm()
    orchestrator = make_orchestrator(llm)
    asyncio.run(orchestrator.warmup())
    assert len(llm.calls) == 1

    failing = make_orchestrator(FakeLLM(fail=True))
    asyncio.run(failing.warmup())  # logged, not raised


def test_legal_terms_steer_search_and_rerank() -> None:
    llm = scripted_llm(analysis={"legal_terms": ["maintenance pendente lite", " "]})
    orchestrator = make_orchestrator(llm)
    calls: list[tuple[str, dict[str, object]]] = []
    search = orchestrator.retriever.search

    def spy(query: str, top_k: int, **kw: object):  # type: ignore[no-untyped-def]
        calls.append((query, kw))
        return search(query, top_k, **kw)  # type: ignore[arg-type]

    orchestrator.retriever.search = spy  # type: ignore[method-assign]
    asyncio.run(orchestrator.answer("money while my case is pending"))

    query, kw = calls[0]
    assert query == "money while my case is pending"
    assert kw["alt_queries"] == ["maintenance pendente lite"]
    assert kw["rerank_query"] == "money while my case is pending (maintenance pendente lite)"


def test_warmup_can_skip_the_llm_ping() -> None:
    llm = scripted_llm()
    asyncio.run(make_orchestrator(llm, warmup_llm=False).warmup())
    assert llm.calls == []  # a remote API would only spend daily quota


def test_light_llm_takes_the_short_calls() -> None:
    main = scripted_llm(translated_answer="अल्फा [1]।")
    light = scripted_llm(query_en="what alpha grounds apply")
    orchestrator = make_orchestrator(main, light=light)

    result = asyncio.run(orchestrator.answer("अल्फा आधार क्या हैं?"))

    assert result.answer == "अल्फा [1]।"
    light_kinds = {s.split()[1] for s, _ in light.calls}
    main_kinds = {s.split()[1] for s, _ in main.calls}
    assert light_kinds == {"translate", "analyse", "check"}  # question, understanding, evidence
    assert main_kinds == {"are", "translate"}  # "You are Kanoon AI" + answer translation
    assert all(s.startswith("You translate answers") for s, _ in main.calls if "translate" in s)
