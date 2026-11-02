"""The hi/kn gold set must mirror the English one (same expected chunks and evidence)."""

import json
from pathlib import Path
from typing import Any

from app.nlp.language import detect_language

ROOT = Path(__file__).resolve().parents[2] / "data" / "evaluation"


def _load(name: str) -> list[dict[str, Any]]:
    lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_multilingual_gold_mirrors_english() -> None:
    english = {g["id"]: g for g in _load("gold_queries.jsonl")}
    translated = _load("gold_queries_multilingual.jsonl")

    assert len(translated) == 2 * len(english)
    assert len({g["id"] for g in translated}) == len(translated)
    for g in translated:
        source = english[g["source_id"]]
        assert g["id"] == f"{source['id']}-{g['language']}"
        assert g["expected_chunk_ids"] == source["expected_chunk_ids"]
        assert g["evidence"] == source["evidence"]  # evidence stays verbatim English
        assert g["status"] == "draft-translated"
        assert detect_language(g["query"]).language == g["language"]
