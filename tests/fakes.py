"""Test doubles for the RAG stack: a tiny corpus, a deterministic embedder, a scripted LLM.

No model weights, GPU, or Ollama needed, so these run in CI.
"""

import hashlib
import json
import math
import re
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

from qdrant_client import QdrantClient

from app.agents.orchestrator import Orchestrator
from app.ingestion.models import Chunk, Document, SourceFile
from app.nlp.language import Language
from app.providers.asr import Transcript
from app.providers.llm import LLMError
from app.providers.translation import LLMTranslator
from app.retrieval.corpus import Corpus
from app.retrieval.index import Retriever
from app.retrieval.store import VectorStore

_SOURCE = SourceFile(path="data/raw/x.pdf", sha256="0" * 64, size_bytes=1)


def make_corpus() -> Corpus:
    """Synthetic corpus (placeholder wording, not real statute text) with the real shapes:
    a section parent with two provisions, a childless section, and judgment chunks."""
    statute = Document(
        doc_id="act1",
        doc_type="statute",
        court_level="legislation",
        title="Example Act, 2000",
        personal_law="hindu",  # like HMA 1955: subject to the applicability gate
        page_count=2,
        sources=[_SOURCE],
    )
    judgment = Document(
        doc_id="sc-test",
        doc_type="judgment",
        court_level="supreme_court",
        title="A v. B",
        court="Supreme Court of India",
        citation="[2024] 1 S.C.R. 1",
        decision_date=date(2024, 1, 2),
        page_count=3,
        sources=[_SOURCE],
    )

    def chunk(chunk_id: str, kind: str, label: str, text: str, parent: str | None = None) -> Chunk:
        doc_id = chunk_id.split(":", 1)[0]
        return Chunk.model_validate(
            {
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "parent_id": parent,
                "kind": kind,
                "label": label,
                "order": 0,
                "text": text,
                "context": f"{doc_id} | {label}",
                "page_start": 1,
                "page_end": 1,
            }
        )

    chunks = [
        chunk(
            "act1:s2",
            "section",
            "Section 2",
            "2. Grounds.— (1) alpha grounds apply. (2) beta waiting period.",
        ),
        chunk("act1:s2:ss1", "provision", "Section 2(1)", "(1) alpha grounds apply.", "act1:s2"),
        chunk("act1:s2:ss2", "provision", "Section 2(2)", "(2) beta waiting period.", "act1:s2"),
        chunk("act1:s3", "section", "Section 3", "3. Gamma registration of records."),
        chunk("sc-test:issue", "judgment_summary", "Issue", "Whether delta custody is allowed."),
        chunk("sc-test:p4", "judgment_paragraph", "Para 4", "4. Delta custody goes to mother."),
    ]
    return Corpus(
        documents={statute.doc_id: statute, judgment.doc_id: judgment},
        chunks={c.chunk_id: c for c in chunks},
    )


class FakeEmbedder:
    """Hashed bag-of-words vectors: texts sharing words are close; fully deterministic."""

    def __init__(self, dimension: int = 64, model_name: str = "fake-embedder") -> None:
        self._dimension = dimension
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self._dimension
        for word in re.findall(r"[a-z]+", text.lower()):
            bucket = int(hashlib.md5(word.encode(), usedforsecurity=False).hexdigest(), 16)
            vec[bucket % self._dimension] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class FakeReranker:
    """Scores a passage by the share of query words it contains (records its inputs)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    @property
    def model_name(self) -> str:
        return "fake-reranker"

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        self.calls.append((query, len(passages)))
        words = set(re.findall(r"[a-z]+", query.lower()))
        return [
            len(words & set(re.findall(r"[a-z]+", p.lower()))) / (len(words) or 1) for p in passages
        ]


class FakeLLM:
    def __init__(
        self,
        reply: str = "Alpha grounds apply [1].",
        fail: bool = False,
        responder: Callable[[str, str], str] | None = None,
    ) -> None:
        self.reply = reply
        self.fail = fail
        self.responder = responder  # (system, prompt) -> reply; overrides ``reply``
        self.calls: list[tuple[str, str]] = []
        self.kwargs: list[dict[str, Any]] = []

    @property
    def model_name(self) -> str:
        return "fake-llm"

    async def generate(
        self,
        system: str,
        prompt: str,
        *,
        temperature: float | None = None,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> str:
        self.calls.append((system, prompt))
        self.kwargs.append(
            {"temperature": temperature, "json_schema": json_schema, "max_tokens": max_tokens}
        )
        if self.fail:
            raise LLMError("fake outage")
        return self.responder(system, prompt) if self.responder else self.reply


def make_store() -> VectorStore:
    return VectorStore(QdrantClient(":memory:"))


def scripted_llm(
    *,
    answer: str = "Alpha grounds apply [1].",
    analysis: dict[str, Any] | None = None,
    assessment: dict[str, Any] | None = None,
    query_en: str | None = None,
    translated_answer: str | Callable[[str], str] | None = None,
    fail: bool = False,
) -> FakeLLM:
    """A FakeLLM that answers each orchestrator call type (routed by system prompt)."""
    base = {
        "in_scope": True,
        "topic": "divorce",
        "religion": "hindu",
        "marriage_type": "unknown",
        "emergency": False,
        "standalone_question": "",
    }

    def responder(system: str, prompt: str) -> str:
        if system.startswith("You analyse questions"):
            data = {**base, **(analysis or {})}
            if not data["standalone_question"]:  # echo the English question by default
                line = next(
                    (ln for ln in prompt.splitlines() if ln.startswith("English translation:")),
                    next(ln for ln in prompt.splitlines() if ln.startswith("User question:")),
                )
                data["standalone_question"] = line.split(":", 1)[1].strip()
            return json.dumps(data)
        if system.startswith("You check whether retrieved"):
            n = prompt.count("\n[")  # sources listed as "[n] heading"
            default = {"relevant": list(range(1, n + 1)), "sufficient": True}
            return json.dumps(assessment or default)
        if system.startswith("You translate questions"):
            return query_en or "translated question"
        if system.startswith("You translate answers"):
            english = prompt.split("English:\n", 1)[1]
            if callable(translated_answer):
                return translated_answer(english)
            return translated_answer if translated_answer is not None else f"T({english})"
        return answer

    return FakeLLM(fail=fail, responder=responder)


def make_orchestrator(
    llm: FakeLLM | None = None, top_k: int = 3, light: FakeLLM | None = None, **kwargs: Any
) -> Orchestrator:
    """In-memory index over :func:`make_corpus`, ready to answer. ``light``: short-call LLM."""
    corpus, embedder, store = make_corpus(), FakeEmbedder(), make_store()
    units = corpus.retrieval_units()
    store.recreate(embedder.dimension)
    store.upsert(units, embedder.embed_documents([c.embed_text for c in units]))
    llm = llm or scripted_llm()
    retriever = Retriever(corpus, embedder, store, mode="hybrid")
    return Orchestrator(
        retriever,
        llm,
        LLMTranslator(llm, light_llm=light),
        top_k=top_k,
        light_llm=light,
        **kwargs,
    )


class FakeASR:
    """Returns a fixed transcript; records (audio size, language hint) per call."""

    def __init__(self, text: str = "what alpha grounds apply", error: Exception | None = None):
        self.text = text
        self.error = error
        self.calls: list[tuple[int, str | None]] = []

    @property
    def model_name(self) -> str:
        return "fake-asr"

    def load(self) -> None:
        return None

    def transcribe(self, audio: bytes, language: Language | None = None) -> Transcript:
        self.calls.append((len(audio), language))
        if self.error is not None:
            raise self.error
        return Transcript(self.text, language or "en", 1.0 if language else 0.9, 2.5)


class FakeTTS:
    """Returns a tiny WAV-like payload; records (text, language) per call."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def load(self, language: Language) -> None:
        return None

    def synthesize(self, text: str, language: Language) -> bytes:
        self.calls.append((text, language))
        if self.error is not None:
            raise self.error
        return b"RIFF....WAVEfmt fake"
