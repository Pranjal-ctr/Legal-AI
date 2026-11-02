"""Evidence assembly, prompt construction, and citation checking for the baseline RAG answer."""

import re
from dataclasses import dataclass, field

from app.ingestion.models import Chunk, Document
from app.nlp.language import Language, answer_language_instruction
from app.retrieval.corpus import Corpus
from app.retrieval.index import RetrievedChunk

_SYSTEM_TEMPLATE = """\
You are Kanoon AI, a research assistant that gives general information about Indian family law.
You do not give legal advice and you are not a lawyer.

Rules:
1. Use ONLY the numbered SOURCES in the user message. Do not use outside knowledge.
2. Support every legal statement with the source number in square brackets, e.g. [1] or [2][3].
3. Never invent section numbers, case names, citations, dates, or quotations. Quote only words
   that appear in the sources, in their original English, inside quotation marks.
4. If the sources do not answer the question, say so plainly and describe what information is
   missing. Do not guess.
5. A judgment shows how a court decided a particular case; describe it as such, not as a rule
   that always applies.
6. If the answer depends on facts the user has not given (for example religion, type of marriage,
   or dates), say which facts matter.
7. {language_rule} Keep it to at most about 250 words.
"""


def build_system_prompt(
    language: Language = "en", romanized: bool = False, glossary: str = ""
) -> str:
    rule = answer_language_instruction(language, romanized)
    prompt = _SYSTEM_TEMPLATE.format(language_rule=rule)
    if glossary:
        prompt += "\nUse these legal terms in the answer:\n" + glossary + "\n"
    return prompt


SYSTEM_PROMPT = build_system_prompt()

_CITATION_RE = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")


@dataclass
class EvidenceItem:
    """One numbered source shown to the LLM: a statute section or a judgment passage."""

    n: int
    unit: Chunk  # what the model reads: parent section for provisions, else the hit itself
    document: Document
    score: float  # best similarity among the hits that mapped to this unit
    matched_chunk_ids: list[str] = field(default_factory=list)  # the retrieved leaf chunks


def assemble_evidence(corpus: Corpus, hits: list[RetrievedChunk]) -> list[EvidenceItem]:
    """Map hits to context units (provision → its full section), dedupe, keep rank order."""
    items: dict[str, EvidenceItem] = {}
    for hit in hits:
        unit = corpus.parent(hit.chunk) or hit.chunk
        item = items.get(unit.chunk_id)
        if item is None:
            item = EvidenceItem(
                n=len(items) + 1,
                unit=unit,
                document=corpus.documents[unit.doc_id],
                score=hit.score,
            )
            items[unit.chunk_id] = item
        item.matched_chunk_ids.append(hit.chunk.chunk_id)
    return list(items.values())


def source_heading(item: EvidenceItem) -> str:
    doc, unit = item.document, item.unit
    if doc.doc_type == "statute":
        return f"{doc.title} — {unit.label}"
    parts = [doc.title, doc.court, doc.citation]
    if doc.decision_date is not None:
        parts.append(f"decided {doc.decision_date.isoformat()}")
    head = ", ".join(p for p in parts if p)
    return f"{head} — {unit.label}"


def build_prompt(question: str, evidence: list[EvidenceItem]) -> str:
    blocks = [f"[{item.n}] {source_heading(item)}\n{item.unit.text}" for item in evidence]
    sources = "\n\n".join(blocks) if blocks else "(no sources found)"
    return f"SOURCES:\n\n{sources}\n\nQUESTION: {question}\n\nAnswer using only the sources."


@dataclass(frozen=True)
class CitationCheck:
    answer: str  # with out-of-range markers removed
    cited: list[int]  # valid source numbers, in first-mention order
    invalid: list[int]  # numbers that matched no source (removed from the answer)


def check_citations(answer: str, source_count: int) -> CitationCheck:
    """Keep ``[n]`` markers that point to a real source; strip the rest."""
    cited: list[int] = []
    invalid: list[int] = []

    def _replace(match: re.Match[str]) -> str:
        valid: list[int] = []
        for raw in re.split(r"\s*[,;]\s*", match.group(1)):
            n = int(raw)
            if 1 <= n <= source_count:
                valid.append(n)
                if n not in cited:
                    cited.append(n)
            elif n not in invalid:
                invalid.append(n)
        return "".join(f"[{n}]" for n in valid)

    cleaned = _CITATION_RE.sub(_replace, answer)
    cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", cleaned)  # tidy spaces left by removed markers
    return CitationCheck(answer=cleaned, cited=cited, invalid=invalid)
