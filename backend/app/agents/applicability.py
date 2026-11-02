"""Applicability gate: does the corpus's personal law (HMA 1955) apply to this user?

Deterministic. The only statute in the corpus is the Hindu Marriage Act, whose s.2 extends it
to Hindus, Buddhists, Jainas and Sikhs. For personal-law topics the gate decides whether HMA
provisions may be presented as applicable, must be withheld, or whether to ask the user first.
Secular topics (domestic violence, dowry) are not gated.
"""

from dataclasses import dataclass
from typing import Literal

from app.agents.understanding import QueryAnalysis, UserFacts
from app.nlp.language import Language

Decision = Literal["applies", "not_applicable", "unknown", "not_gated"]

PERSONAL_LAW_TOPICS = frozenset(
    {"marriage", "divorce", "maintenance", "child_custody", "adoption", "succession"}
)
HMA_RELIGIONS = frozenset({"hindu", "sikh", "jain", "buddhist"})
OTHER_PERSONAL_LAWS = frozenset({"muslim", "christian", "parsi", "jewish"})


@dataclass(frozen=True)
class Applicability:
    decision: Decision
    ask_user: bool  # True → reply with a clarifying question instead of an answer
    religion: str
    marriage_type: str


def merge_facts(analysis: QueryAnalysis, facts: UserFacts | None) -> QueryAnalysis:
    """User-stated facts override extracted ones."""
    if facts is None:
        return analysis
    update: dict[str, str] = {}
    if facts.religion is not None and facts.religion != "unspecified":
        update["religion"] = facts.religion
    if facts.marriage_type is not None:
        update["marriage_type"] = facts.marriage_type
    return analysis.model_copy(update=update) if update else analysis


def fill_facts(
    analysis: QueryAnalysis, facts: UserFacts | None, profile: UserFacts | None
) -> UserFacts | None:
    """Effective facts. Precedence: this request's facts (an answer to a clarification), then
    what the current question states, then the session profile (earlier answers), which only
    fills fields that are still unknown."""
    if profile is None:
        return facts
    religion = facts.religion if facts else None
    marriage_type = facts.marriage_type if facts else None
    if religion is None and analysis.religion == "unknown":
        religion = profile.religion
    if marriage_type is None and analysis.marriage_type == "unknown":
        marriage_type = profile.marriage_type
    if religion is None and marriage_type is None:
        return None
    return UserFacts(religion=religion, marriage_type=marriage_type)


def assess(analysis: QueryAnalysis, facts: UserFacts | None = None) -> Applicability:
    a = merge_facts(analysis, facts)
    unspecified = facts is not None and facts.religion == "unspecified"
    if a.topic not in PERSONAL_LAW_TOPICS:
        decision: Decision = "not_gated"
    elif (
        a.marriage_type == "special_marriage_act"
        or a.religion in OTHER_PERSONAL_LAWS
        or a.marriage_type in ("muslim_nikah", "christian")
    ):
        decision = "not_applicable"
    elif a.religion in HMA_RELIGIONS or a.marriage_type == "hindu_rites":
        decision = "applies"
    else:
        decision = "unknown"
    return Applicability(
        decision=decision,
        ask_user=decision == "unknown" and not unspecified,
        religion=a.religion,
        marriage_type=a.marriage_type,
    )


# ---- user-facing texts (localised) --------------------------------------------------------

CLARIFY_QUESTION: dict[Language, str] = {
    "en": "Which law applies depends on your religion or how the marriage was performed. "
    "Which of these fits your situation?",
    "hi": "कौन-सा कानून लागू होगा, यह आपके धर्म या विवाह के प्रकार पर निर्भर करता है। "
    "आपकी स्थिति इनमें से किससे मेल खाती है?",
    "kn": "ಯಾವ ಕಾನೂನು ಅನ್ವಯಿಸುತ್ತದೆ ಎಂಬುದು ನಿಮ್ಮ ಧರ್ಮ ಅಥವಾ ವಿವಾಹ ನಡೆದ ರೀತಿಯನ್ನು ಅವಲಂಬಿಸಿದೆ. "
    "ನಿಮ್ಮ ಪರಿಸ್ಥಿತಿಗೆ ಇವುಗಳಲ್ಲಿ ಯಾವುದು ಹೊಂದುತ್ತದೆ?",
}

# (fact field, value, label per language)
CLARIFY_OPTIONS: list[tuple[str, str, dict[Language, str]]] = [
    ("religion", "hindu", {
        "en": "Hindu, Sikh, Jain or Buddhist",
        "hi": "हिंदू, सिख, जैन या बौद्ध",
        "kn": "ಹಿಂದೂ, ಸಿಖ್, ಜೈನ ಅಥವಾ ಬೌದ್ಧ",
    }),
    ("religion", "muslim", {"en": "Muslim", "hi": "मुस्लिम", "kn": "ಮುಸ್ಲಿಂ"}),
    ("religion", "christian", {"en": "Christian", "hi": "ईसाई", "kn": "ಕ್ರಿಶ್ಚಿಯನ್"}),
    ("religion", "parsi", {"en": "Parsi", "hi": "पारसी", "kn": "ಪಾರ್ಸಿ"}),
    ("marriage_type", "special_marriage_act", {
        "en": "Inter-faith or court marriage (Special Marriage Act)",
        "hi": "अंतर-धार्मिक या कोर्ट मैरिज (विशेष विवाह अधिनियम)",
        "kn": "ಅಂತರ್ಧರ್ಮೀಯ ಅಥವಾ ನ್ಯಾಯಾಲಯ ವಿವಾಹ (ವಿಶೇಷ ವಿವಾಹ ಕಾಯ್ದೆ)",
    }),
    ("religion", "unspecified", {
        "en": "Not sure / answer generally",
        "hi": "पता नहीं / सामान्य जानकारी दें",
        "kn": "ಗೊತ್ತಿಲ್ಲ / ಸಾಮಾನ್ಯ ಮಾಹಿತಿ ನೀಡಿ",
    }),
]  # fmt: skip

NOT_APPLICABLE_NOTICE: dict[Language, str] = {
    "en": "The Hindu Marriage Act, 1955 — the only statute in this system — applies to Hindus, "
    "Buddhists, Jains and Sikhs, and may not govern your marriage. The law that applies to you "
    "is not yet in this system, so only related court judgments are shown. Please consult a "
    "lawyer or your District Legal Services Authority.",
    "hi": "हिंदू विवाह अधिनियम, 1955 — इस प्रणाली में उपलब्ध एकमात्र कानून — हिंदू, बौद्ध, जैन और "
    "सिख पर लागू होता है, और संभव है कि यह आपके विवाह पर लागू न हो। आप पर लागू होने वाला कानून "
    "अभी इस प्रणाली में नहीं है, इसलिए केवल संबंधित अदालती फैसले दिखाए गए हैं। कृपया किसी वकील या "
    "ज़िला विधिक सेवा प्राधिकरण से सलाह लें।",
    "kn": "ಹಿಂದೂ ವಿವಾಹ ಕಾಯ್ದೆ, 1955 — ಈ ವ್ಯವಸ್ಥೆಯಲ್ಲಿರುವ ಏಕೈಕ ಕಾನೂನು — ಹಿಂದೂ, ಬೌದ್ಧ, ಜೈನ ಮತ್ತು ಸಿಖ್ಖರಿಗೆ "
    "ಅನ್ವಯಿಸುತ್ತದೆ ಮತ್ತು ನಿಮ್ಮ ವಿವಾಹಕ್ಕೆ ಅನ್ವಯಿಸದಿರಬಹುದು. ನಿಮಗೆ ಅನ್ವಯಿಸುವ ಕಾನೂನು ಇನ್ನೂ ಈ "
    "ವ್ಯವಸ್ಥೆಯಲ್ಲಿಲ್ಲ, ಆದ್ದರಿಂದ ಸಂಬಂಧಿತ ನ್ಯಾಯಾಲಯದ ತೀರ್ಪುಗಳನ್ನು ಮಾತ್ರ ತೋರಿಸಲಾಗಿದೆ. ದಯವಿಟ್ಟು ವಕೀಲರನ್ನು "
    "ಅಥವಾ ಜಿಲ್ಲಾ ಕಾನೂನು ಸೇವಾ ಪ್ರಾಧಿಕಾರವನ್ನು ಸಂಪರ್ಕಿಸಿ.",
}

UNSPECIFIED_NOTICE: dict[Language, str] = {
    "en": "This answer uses the Hindu Marriage Act, 1955, which applies to Hindus, Buddhists, "
    "Jains and Sikhs. A different law may apply to other marriages.",
    "hi": "यह उत्तर हिंदू विवाह अधिनियम, 1955 पर आधारित है, जो हिंदू, बौद्ध, जैन और सिख पर लागू होता है। "
    "अन्य विवाहों पर कोई अलग कानून लागू हो सकता है।",
    "kn": "ಈ ಉತ್ತರವು ಹಿಂದೂ ವಿವಾಹ ಕಾಯ್ದೆ, 1955 ಅನ್ನು ಆಧರಿಸಿದೆ, ಇದು ಹಿಂದೂ, ಬೌದ್ಧ, ಜೈನ ಮತ್ತು ಸಿಖ್ಖರಿಗೆ "
    "ಅನ್ವಯಿಸುತ್ತದೆ. ಇತರ ವಿವಾಹಗಳಿಗೆ ಬೇರೆ ಕಾನೂನು ಅನ್ವಯಿಸಬಹುದು.",
}

EMERGENCY_NOTICE: dict[Language, str] = {
    "en": "If you are in immediate danger, call 112 (emergency) or 181 (women helpline).",
    "hi": "यदि आप तत्काल खतरे में हैं, तो 112 (आपातकालीन) या 181 (महिला हेल्पलाइन) पर कॉल करें।",
    "kn": "ನೀವು ತಕ್ಷಣದ ಅಪಾಯದಲ್ಲಿದ್ದರೆ, 112 (ತುರ್ತು) ಅಥವಾ 181 (ಮಹಿಳಾ ಸಹಾಯವಾಣಿ) ಗೆ ಕರೆ ಮಾಡಿ.",
}

OUT_OF_SCOPE_ANSWER: dict[Language, str] = {
    "en": "I can only give information about Indian family law (marriage, divorce, maintenance, "
    "custody, domestic violence). This question seems to be about something else.",
    "hi": "मैं केवल भारतीय पारिवारिक कानून (विवाह, तलाक, भरण-पोषण, कस्टडी, घरेलू हिंसा) के बारे में "
    "जानकारी दे सकता हूँ। यह प्रश्न किसी अन्य विषय का लगता है।",
    "kn": "ನಾನು ಭಾರತೀಯ ಕೌಟುಂಬಿಕ ಕಾನೂನು (ವಿವಾಹ, ವಿಚ್ಛೇದನ, ಜೀವನಾಂಶ, ಪಾಲನೆ, ಕೌಟುಂಬಿಕ ಹಿಂಸೆ) ಕುರಿತು ಮಾತ್ರ "
    "ಮಾಹಿತಿ ನೀಡಬಲ್ಲೆ. ಈ ಪ್ರಶ್ನೆ ಬೇರೆ ವಿಷಯದ ಬಗ್ಗೆ ಇದೆ ಎಂದು ತೋರುತ್ತದೆ.",
}

GENERATOR_NOT_APPLICABLE = (
    "Applicability: the user's marriage is likely NOT governed by the Hindu Marriage Act. Do not "
    "present Hindu Marriage Act provisions as applying to them; describe only what the court "
    "judgments in the sources say, as examples."
)
GENERATOR_UNSPECIFIED = (
    "Applicability: the user's religion is not known. When you rely on the Hindu Marriage Act, "
    "say that it applies to Hindus, Buddhists, Jains and Sikhs."
)
