"""Checks on the real ingested corpus (data/processed). Skipped when it has not been built.

Build it first with ``uv run python -m scripts.ingest``. The source PDFs are git-ignored, so CI
skips these tests; the gold-query file itself is still validated for shape.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHUNKS = ROOT / "data" / "processed" / "chunks.jsonl"
DOCUMENTS = ROOT / "data" / "processed" / "documents.jsonl"
GOLD = ROOT / "data" / "evaluation" / "gold_queries.jsonl"

needs_corpus = pytest.mark.skipif(
    not CHUNKS.exists(), reason="run `python -m scripts.ingest` first"
)


def _load(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_gold_queries_are_well_formed() -> None:
    gold = _load(GOLD)
    assert len(gold) == 20
    assert len({g["id"] for g in gold}) == 20
    for g in gold:
        assert g["query"] and g["evidence"] and g["expected_chunk_ids"]


@needs_corpus
def test_gold_queries_resolve_to_chunks_containing_evidence() -> None:
    chunks = {c["chunk_id"]: c for c in _load(CHUNKS)}
    for g in _load(GOLD):
        expected = g["expected_chunk_ids"]
        assert isinstance(expected, list)
        missing = [cid for cid in expected if cid not in chunks]
        assert not missing, f"{g['id']}: unknown chunk ids {missing}"
        text = " ".join(str(chunks[cid]["text"]) for cid in expected)
        assert g["evidence"] in text, f"{g['id']}: evidence not found verbatim"


@needs_corpus
def test_hma_structure() -> None:
    chunks = [c for c in _load(CHUNKS) if c["doc_id"] == "hma1955"]
    sections = [c["chunk_id"] for c in chunks if c["kind"] == "section"]
    assert len(sections) == 37  # s1-s30 plus 13A, 13B, 21A, 21B, 21C, 23A, 28A
    ids = {c["chunk_id"] for c in chunks}
    for cid in ("hma1955:s13:ss1:cl(ia)", "hma1955:s13:ss1A:cl(ii)", "hma1955:s23:ss1:cl(bb)"):
        assert cid in ids
    s13 = next(c for c in chunks if c["chunk_id"] == "hma1955:s13")
    assert any("Act 6 of 2019" in a for a in s13["amendments"])  # leprosy ground omitted


@needs_corpus
def test_documents_and_chunks_are_consistent() -> None:
    documents = _load(DOCUMENTS)
    chunks = _load(CHUNKS)
    doc_ids = {d["doc_id"] for d in documents}
    assert len(doc_ids) == len(documents)
    assert {c["doc_id"] for c in chunks} == doc_ids  # every document produced chunks
    assert len({c["chunk_id"] for c in chunks}) == len(chunks)
    for chunk in chunks:
        assert chunk["text"].strip()
        assert chunk["page_start"] <= chunk["page_end"]
    sc = [d for d in documents if d["court_level"] == "supreme_court"]
    assert all(d["citation"] and d["decision_date"] for d in sc)
