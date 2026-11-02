from app.nlp.speech_text import english_number, speech_clauses


def test_english_numbers() -> None:
    assert english_number(13) == "thirteen"
    assert english_number(40) == "forty"
    assert english_number(125) == "one hundred twenty five"
    assert english_number(100000) == "one hundred thousand"


def test_english_answer_drops_markers_and_reads_numbers() -> None:
    clauses = speech_clauses(
        "Under Section 13(1) of the Act, 1955, a marriage may be dissolved [3], [5]. "
        "Maintenance of Rs.4,000/- per month [2].",
        "en",
    )

    assert clauses == [
        "Under Section thirteen one of the Act",
        "nineteen fifty five",
        "a marriage may be dissolved",
        "Maintenance of rupees four thousand per month",
    ]


def test_hindi_keeps_matras_and_reads_the_translation_of_a_quote() -> None:
    clauses = speech_clauses(
        'हाँ, तलाक मांगा जा सकता है [3]। धारा 13 के तहत, विवाह "may be dissolved" '
        "(भंग किया जा सकता है) [3]।",
        "hi",
    )

    assert clauses == [
        "हाँ",
        "तलाक मांगा जा सकता है",
        "धारा एक तीन के तहत",
        "विवाह भंग किया जा सकता है",
    ]


def test_kannada_digits_and_latin_words_are_handled() -> None:
    clauses = speech_clauses("ಕಾಯ್ದೆ ೧೯೫೫ ರ Section ಅಡಿಯಲ್ಲಿ [1].", "kn")

    assert clauses == ["ಕಾಯ್ದೆ ಒಂದು ಒಂಬತ್ತು ಐದು ಐದು ರ ಅಡಿಯಲ್ಲಿ"]


def test_nothing_speakable() -> None:
    assert speech_clauses("[1] [2] ...", "en") == []
    assert speech_clauses("Only English words", "hi") == []
