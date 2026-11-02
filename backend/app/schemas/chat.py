from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.agents.understanding import UserFacts
from app.ingestion.models import DocType

Message = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


LanguageCode = Literal["en", "hi", "kn"]
SessionId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]


class ChatRequest(BaseModel):
    message: Message
    language: LanguageCode | None = Field(
        default=None, description="Answer language; detected from the message when omitted."
    )
    facts: UserFacts | None = Field(
        default=None, description="Facts the user stated, e.g. an answer to a clarification."
    )
    session_id: SessionId | None = Field(
        default=None,
        description="Continue a conversation. Omitted, unknown or expired: a new one starts.",
    )


class Source(BaseModel):
    """A numbered source shown to the model; ``[n]`` in the answer refers to ``n`` here."""

    n: int
    chunk_id: str  # the passage shown (a full section for statute provisions)
    matched_chunk_ids: list[str]  # the retrieved leaf chunks that led to it
    doc_id: str
    doc_type: DocType
    title: str
    label: str  # e.g. "Section 13" or "Para 15"
    court: str | None
    citation: str | None
    decision_date: date | None
    page_start: int
    page_end: int
    text: str  # verbatim source text
    score: float
    cited: bool


class ClarifyOptionOut(BaseModel):
    field: Literal["religion", "marriage_type"]
    value: str
    label: str  # in the user's language


class ClarificationOut(BaseModel):
    question: str
    options: list[ClarifyOptionOut]


class AnalysisOut(BaseModel):
    topic: str
    religion: str
    marriage_type: str
    in_scope: bool
    applicability: str | None  # applies | not_applicable | unknown | not_gated


class ValidationOut(BaseModel):
    invalid_citations: list[int]
    verified_quotes: int
    unquoted: list[str] = Field(
        description="Non-verbatim 'quotations' whose quote marks were removed."
    )
    regenerated: bool
    translation_ok: bool


class TraceStepOut(BaseModel):
    step: str
    ms: int
    detail: dict[str, Any]


class ChatResponse(BaseModel):
    session_id: str = Field(description="Send back to continue this conversation.")
    kind: Literal["answer", "clarification", "out_of_scope"]
    answer: str = Field(description="In the user's language.")
    answer_en: str = Field(description="The verified English answer (canonical, auditable).")
    grounded: bool = Field(description="True when the answer cites at least one source.")
    sources: list[Source]
    model: str
    language: LanguageCode
    romanized: bool = Field(description="Hindi written in Latin script (Hinglish).")
    english_query: str = Field(description="Standalone English question used for search.")
    notices: list[str] = Field(description="Applicability / emergency notices to show first.")
    emergency: bool
    clarification: ClarificationOut | None
    analysis: AnalysisOut | None
    validation: ValidationOut
    rounds: int = Field(description="Retrieval rounds used (0 when no search ran).")
    trace: list[TraceStepOut]


class SessionMessage(BaseModel):
    role: Literal["user", "assistant"]
    kind: str
    language: LanguageCode
    text: str
    text_en: str
    created_at: float


class SessionOut(BaseModel):
    session_id: str
    created_at: float
    updated_at: float
    facts: UserFacts
    messages: list[SessionMessage]


class FeedbackRequest(BaseModel):
    session_id: SessionId
    rating: Literal["up", "down"]
    language: LanguageCode
    question: Message
    answer_en: Annotated[str, StringConstraints(max_length=20000)]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ""
