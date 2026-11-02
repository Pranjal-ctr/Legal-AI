import asyncio
import json

import pytest

from app.agents.applicability import (
    CLARIFY_OPTIONS,
    CLARIFY_QUESTION,
    EMERGENCY_NOTICE,
    NOT_APPLICABLE_NOTICE,
    assess,
)
from app.agents.understanding import (
    QueryAnalysis,
    QueryUnderstanding,
    UserFacts,
    rule_facts,
)
from tests.fakes import FakeLLM


def _analysis(**kw: object) -> QueryAnalysis:
    base: dict[str, object] = {
        "in_scope": True,
        "topic": "divorce",
        "standalone_question": "q",
    }
    return QueryAnalysis.model_validate({**base, **kw})


@pytest.mark.parametrize(
    ("text", "religion", "marriage"),
    [
        ("Hindu marriage divorce", "hindu", "unknown"),
        ("We had a nikah in 2019", "muslim", "unknown"),
        ("मेरा निकाह हुआ था", "muslim", "unknown"),
        ("ನಾವು ಹಿಂದೂ ಸಂಪ್ರದಾಯದಂತೆ ಮದುವೆಯಾದೆವು", "hindu", "unknown"),
        ("registered under the Special Marriage Act", "unknown", "special_marriage_act"),
        ("My name is Mohammed Sharma", "unknown", "unknown"),  # never infer from names
        ("I am Hindu and she is Christian", "unknown", "unknown"),  # inter-faith: not decided
        ("church wedding last year", "christian", "unknown"),
    ],
)
def test_rule_facts_only_explicit_statements(text: str, religion: str, marriage: str) -> None:
    assert rule_facts([text]) == (religion, marriage)


def test_llm_analysis_is_parsed_and_rules_fill_unknown_religion() -> None:
    reply = json.dumps(
        {
            "in_scope": True,
            "topic": "divorce",
            "religion": "unknown",
            "marriage_type": "unknown",
            "emergency": False,
            "standalone_question": "Can a wife get divorce after nikah?",
        }
    )
    llm = FakeLLM(reply=reply)

    analysis = asyncio.run(QueryUnderstanding(llm).analyse("nikah ke baad talaq?", "divorce?"))

    assert analysis.religion == "muslim"  # rule saw "nikah"
    assert analysis.standalone_question == "Can a wife get divorce after nikah?"
    assert llm.kwargs[0]["json_schema"] == QueryAnalysis.model_json_schema()
    assert llm.kwargs[0]["temperature"] == 0.0


def test_history_is_passed_for_follow_up_rewriting() -> None:
    llm = FakeLLM(
        reply=json.dumps({"in_scope": True, "topic": "divorce", "standalone_question": "x"})
    )

    asyncio.run(
        QueryUnderstanding(llm).analyse(
            "and the waiting period?", "and the waiting period?", [("user", "mutual divorce?")]
        )
    )

    assert "user: mutual divorce?" in llm.calls[0][1]


@pytest.mark.parametrize("reply", ["not json", json.dumps({"topic": "nonsense"})])
def test_invalid_llm_output_falls_back_to_rules(reply: str) -> None:
    analysis = asyncio.run(
        QueryUnderstanding(FakeLLM(reply=reply)).analyse("Hindu divorce?", "Hindu divorce?")
    )

    assert analysis.in_scope is True  # fallback never refuses
    assert analysis.religion == "hindu"
    assert analysis.standalone_question == "Hindu divorce?"


def test_llm_outage_falls_back_to_rules() -> None:
    analysis = asyncio.run(QueryUnderstanding(FakeLLM(fail=True)).analyse("q", "q"))

    assert analysis.topic == "other_family_law"


@pytest.mark.parametrize(
    ("kw", "decision", "ask"),
    [
        ({"religion": "hindu"}, "applies", False),
        ({"religion": "sikh"}, "applies", False),
        ({"marriage_type": "hindu_rites"}, "applies", False),
        ({"religion": "muslim"}, "not_applicable", False),
        ({"religion": "hindu", "marriage_type": "special_marriage_act"}, "not_applicable", False),
        ({"marriage_type": "muslim_nikah"}, "not_applicable", False),
        ({}, "unknown", True),
        ({"topic": "domestic_violence"}, "not_gated", False),
        ({"topic": "dowry", "religion": "muslim"}, "not_gated", False),
    ],
)
def test_applicability_gate(kw: dict[str, str], decision: str, ask: bool) -> None:
    result = assess(_analysis(**kw))

    assert (result.decision, result.ask_user) == (decision, ask)


def test_user_facts_override_and_unspecified_skips_the_question() -> None:
    assert assess(_analysis(), UserFacts(religion="hindu")).decision == "applies"
    assert assess(_analysis(religion="hindu"), UserFacts(religion="parsi")).decision == (
        "not_applicable"
    )
    unspecified = assess(_analysis(), UserFacts(religion="unspecified"))
    assert (unspecified.decision, unspecified.ask_user) == ("unknown", False)


def test_localised_texts_exist_for_every_language() -> None:
    for texts in (CLARIFY_QUESTION, NOT_APPLICABLE_NOTICE, EMERGENCY_NOTICE):
        assert set(texts) == {"en", "hi", "kn"}
    for _field, _value, labels in CLARIFY_OPTIONS:
        assert set(labels) == {"en", "hi", "kn"}
    assert "112" in EMERGENCY_NOTICE["hi"]
