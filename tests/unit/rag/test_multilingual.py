import asyncio

import pytest

from app.nlp.glossary import glossary_lines, load_glossary, terms_in
from app.nlp.language import answer_language_instruction, detect_language
from app.providers.translation import LLMTranslator
from app.rag.prompt import build_system_prompt
from tests.fakes import FakeLLM, make_orchestrator, scripted_llm


@pytest.mark.parametrize(
    ("text", "language", "romanized"),
    [
        ("What are the grounds for divorce?", "en", False),
        ("तलाक के आधार क्या हैं?", "hi", False),
        ("ವಿಚ್ಛೇದನಕ್ಕೆ ಆಧಾರಗಳು ಯಾವುವು?", "kn", False),
        ("Mera pati mujhe talaq nahi de raha, kya karu?", "hi", True),
        ("kya main maintenance claim kar sakti hoon", "hi", True),
        ("Section 498A ke under kya hota hai", "hi", True),
        ("Is the Hindu Marriage Act applicable to Sikhs?", "en", False),
        ("Can I file in Bangalore? ನಾನು ಬೆಂಗಳೂರಿನಲ್ಲಿ ಅರ್ಜಿ ಸಲ್ಲಿಸಬಹುದೇ?", "kn", False),
        ("HMA धारा 13 क्या है?", "hi", False),
        ("", "en", False),
    ],
)
def test_detect_language(text: str, language: str, romanized: bool) -> None:
    detected = detect_language(text)

    assert (detected.language, detected.romanized) == (language, romanized)


def test_answer_language_instruction() -> None:
    assert answer_language_instruction("en") == "Write the answer in English."
    assert "Devanagari" in answer_language_instruction("hi")
    assert "Latin script" in answer_language_instruction("hi", romanized=True)
    assert "Kannada script" in answer_language_instruction("kn")


def test_glossary_loads_and_matches_terms_in_each_language() -> None:
    glossary = load_glossary()
    assert len(glossary) >= 20
    assert all(t.hi and t.kn for t in glossary)

    assert [t.en for t in terms_in("तलाक और भरण-पोषण", "hi")] == ["divorce", "maintenance"]
    assert [t.en for t in terms_in("ವಿಚ್ಛೇದನ", "kn")] == ["divorce"]
    assert "cruelty" in [t.en for t in terms_in("Divorce on CRUELTY", "en")]

    lines = glossary_lines(terms_in("divorce", "en"), "hi")
    assert lines == "- divorce = तलाक / विवाह-विच्छेद"
    assert glossary_lines(terms_in("divorce", "en"), "en") == ""


def test_system_prompt_carries_language_rule_and_glossary() -> None:
    prompt = build_system_prompt("kn", glossary="- divorce = ವಿಚ್ಛೇದನ")

    assert "Kannada" in prompt
    assert "original English" in prompt  # quotes stay verbatim English
    assert prompt.rstrip().endswith("- divorce = ವಿಚ್ಛೇದನ")


def test_translator_sends_glossary_hints_and_cleans_output() -> None:
    llm = FakeLLM(reply='  "Is cruelty a ground for divorce?"  ')
    translator = LLMTranslator(llm)

    english = asyncio.run(translator.to_english("क्या क्रूरता तलाक का आधार है?", "hi"))

    assert english == "Is cruelty a ground for divorce?"
    system, prompt = llm.calls[0]
    assert "ONLY the English translation" in system
    assert "क्रूरता = cruelty" in prompt
    assert "Hindi question" in prompt
    assert llm.kwargs[0]["temperature"] == 0.0


def test_translator_passes_english_through_without_calling_the_llm() -> None:
    llm = FakeLLM()

    assert asyncio.run(LLMTranslator(llm).to_english("hello", "en")) == "hello"
    assert llm.calls == []


def test_explicit_language_overrides_detection() -> None:
    llm = scripted_llm(translated_answer=lambda english: "हिंदी: " + english)

    result = asyncio.run(make_orchestrator(llm).answer("what alpha grounds apply", language="hi"))

    assert result.language == "hi"
    assert result.answer == "हिंदी: Alpha grounds apply [1]."
