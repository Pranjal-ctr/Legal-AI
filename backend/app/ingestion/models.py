"""Data model for ingested documents and chunks (serialised to JSONL in ``data/processed``)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

DocType = Literal["statute", "judgment"]
CourtLevel = Literal["legislation", "supreme_court", "high_court"]
ChunkKind = Literal[
    "section",  # parent: a full statute section (LLM context)
    "provision",  # child: sub-section / clause / proviso / explanation (retrieval unit)
    "judgment_summary",  # parent-less summary blocks of a reported judgment (issue, headnotes)
    "judgment_paragraph",  # child: numbered paragraph(s) of a judgment
]


class Page(BaseModel):
    """One PDF page of extracted text, 1-based page number."""

    number: int
    text: str


class SourceFile(BaseModel):
    """A file on disk that contributes to a document (duplicates collapse onto one document)."""

    path: str  # repo-relative, forward slashes
    sha256: str
    size_bytes: int
    topic: str | None = None  # from the dataset folder, e.g. "divorce"


class Document(BaseModel):
    doc_id: str
    doc_type: DocType
    court_level: CourtLevel
    title: str
    language: str = "en"
    court: str | None = None
    citation: str | None = None  # e.g. "[2024] 7 S.C.R. 933 : 2024 INSC 517" or "2026:KHC:57008"
    case_number: str | None = None
    decision_date: date | None = None
    bench: str | None = None
    result: str | None = None
    topics: list[str] = Field(default_factory=list)
    statutes_cited: list[str] = Field(default_factory=list)  # act ids, see text.ACT_PATTERNS
    personal_law: str | None = None  # applicability gate for statutes, e.g. "hindu"
    enacted_on: date | None = None
    notes: list[str] = Field(default_factory=list)  # e.g. statute footnotes not tied to a section
    page_count: int
    sources: list[SourceFile]


class Chunk(BaseModel):
    chunk_id: str  # stable, e.g. "hma1955:s13:ss1:cl(ia)" or "sc-1a2b3c4d5e:p15"
    doc_id: str
    parent_id: str | None = None
    kind: ChunkKind
    label: str  # human-readable locator, e.g. "Section 13(1)(ia)" or "Para 15"
    order: int  # position within the document
    text: str  # verbatim (cleaned) source text: this is what gets cited
    context: str  # contextual header prepended before embedding
    page_start: int
    page_end: int
    amendments: list[str] = Field(default_factory=list)  # statute footnotes for this section
    statutes_cited: list[str] = Field(default_factory=list)

    @property
    def embed_text(self) -> str:
        return f"{self.context}\n{self.text}"
