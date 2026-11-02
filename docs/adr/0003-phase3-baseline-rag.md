# ADR 0003 — Phase 3 baseline RAG: dense bge-m3 + embedded Qdrant + local LLM via Ollama

- **Status:** Accepted (Phase 3, 2026-11-01)

## Context

Phase 3 needs an end-to-end, measurable baseline: question → retrieval → grounded answer with
citations → minimal chat UI. Later phases add hybrid retrieval and reranking (4), multilingual
input (5), query understanding (6), agentic control (7) and memory (8). The baseline should be
simple, use the target components where it costs little, and run on the development machine:
Windows, an RTX 4060 Laptop GPU with 8 GB, and a nearly full C: drive.

## Decision

- **Retrieval units = leaf chunks** (`Corpus.retrieval_units()`): provisions, judgment
  paragraphs and summaries, and sections that have no provisions. That is 1454 of 1491 chunks.
  Each is embedded as `context` header + verbatim text. Parent sections are **not** embedded.
  When a provision is retrieved, its full section is what the LLM reads (`assemble_evidence`),
  and duplicates are merged.
- **Embeddings:** `BAAI/bge-m3` dense vectors through sentence-transformers, fp16 on CUDA,
  `max_seq_length` 1024 (the longest chunk is about 700 tokens). Weights live in
  `models/hf` on D:. They load from the local snapshot path, so start-up makes no Hub calls.
  `torch` comes from the cu128 index on Windows (`embed` extra; not installed in CI).
- **Vector store:** Qdrant in **embedded mode** (`data/index/qdrant`). No server is needed.
  `LEGALAI_QDRANT_URL` switches to a Qdrant server with the same code. Point ids are
  `uuid5(chunk_id)`. The payload holds only `chunk_id`, `doc_id` and `kind`; the corpus JSONL
  stays the source of truth for text. `data/index/index_meta.json` records the model and a
  corpus fingerprint, and the API refuses to answer from a stale or mismatched index (503 with
  the rebuild command).
- **LLM:** `gemma4:e4b` served by local **Ollama** (`/api/chat`, non-streaming,
  temperature 0.1, `think: false`) behind an `LLMProvider` protocol.
- **Grounding:** numbered sources `[n]` and a strict evidence-only system prompt.
  `check_citations` keeps valid markers and strips out-of-range ones. `grounded` = at least
  one valid citation, and the UI warns when an answer has none.
- **API:** `POST /api/v1/chat` (single turn, English). The service is built lazily on the
  first request. If ingest output or the index is missing, the endpoint returns 503 with the
  command to run.

## Baseline results (`python -m scripts.eval_retrieval`, 20 draft gold queries, k = 6)

| hit@6 | doc-hit@6 | recall@6 | MRR |
|---|---|---|---|
| 0.75 | 1.00 | 0.70 | 0.62 |

Misses: g16, g19 and g20 retrieve the right judgment but a neighbouring paragraph instead of
the gold summary chunk. g18 retrieves the right judgment's paragraphs but not headnote 4.
g04 (cruelty → HMA s.13(1)(ia)) is a real miss: judgment paragraphs about cruelty outrank the
short statute clause. k = 10 does not change hit rate or MRR (recall 0.725).

Latency once warm: about 1–3 s retrieval and 6–7 s generation. The first request also loads
both models (about 1–2 min).

## Consequences

- Phase 4 should target g04-type misses with BM25 + RRF + bge-reranker-v2-m3 and consider a
  statute prior. The eval script and gold set are the regression harness.
- `grounded` only counts citations. A refusal that cites sources still counts as grounded.
  Claim-level citation validation belongs to a later phase.
- Embedded Qdrant takes a file lock: stop the API before running `scripts.build_index`.
- On 8 GB of VRAM, bge-m3 (about 1.1 GB) and gemma4:e4b share the GPU. Set
  `LEGALAI_EMBEDDING_DEVICE=cpu` if the GPU runs out of memory.
