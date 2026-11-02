"""Read-only view of the ingested corpus (``data/processed/{documents,chunks}.jsonl``)."""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from app.ingestion.models import Chunk, Document


class CorpusNotFoundError(FileNotFoundError):
    """Ingestion output is missing: run ``python -m scripts.ingest`` first."""


def _read_jsonl(path: Path) -> Iterable[str]:
    if not path.is_file():
        raise CorpusNotFoundError(f"{path} not found; run `python -m scripts.ingest` first")
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield line


@dataclass(frozen=True)
class Corpus:
    documents: dict[str, Document]
    chunks: dict[str, Chunk]  # insertion order = ingest order
    _parents: frozenset[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        parents = frozenset(c.parent_id for c in self.chunks.values() if c.parent_id)
        object.__setattr__(self, "_parents", parents)

    @classmethod
    def load(cls, processed_dir: Path) -> "Corpus":
        documents = {
            d.doc_id: d
            for d in (
                Document.model_validate_json(line)
                for line in _read_jsonl(processed_dir / "documents.jsonl")
            )
        }
        chunks = {
            c.chunk_id: c
            for c in (
                Chunk.model_validate_json(line)
                for line in _read_jsonl(processed_dir / "chunks.jsonl")
            )
        }
        return cls(documents=documents, chunks=chunks)

    def retrieval_units(self) -> list[Chunk]:
        """Leaf chunks: provisions, judgment paragraphs/summaries, and childless sections.

        Parents (full sections) are not embedded; they are attached as context at answer time.
        """
        return [c for c in self.chunks.values() if c.chunk_id not in self._parents]

    def parent(self, chunk: Chunk) -> Chunk | None:
        return self.chunks.get(chunk.parent_id) if chunk.parent_id else None

    def fingerprint(self) -> str:
        """Short content hash used to detect a stale index after re-ingestion."""
        digest = hashlib.sha256()
        for chunk in self.retrieval_units():
            digest.update(json.dumps([chunk.chunk_id, chunk.embed_text]).encode("utf-8"))
        return digest.hexdigest()[:16]
