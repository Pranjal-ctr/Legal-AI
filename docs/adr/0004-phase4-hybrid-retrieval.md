# ADR 0004 — Phase 4 hybrid retrieval: dense + BM25 with RRF; reranking optional, off by default

- **Status:** Accepted (Phase 4, 2026-11-01)

## Context

The Phase 3 dense baseline missed g04 ("divorce because of cruelty"): long judgment paragraphs
about cruelty outranked the short HMA s.13(1)(ia) clause. The architecture plans
`bge-m3 dense + BM25 → RRF → bge-reranker-v2-m3`.

## Decision

- **BM25** (`app/retrieval/bm25.py`): an in-memory Okapi BM25 (k1 1.5, b 0.75) over the same
  leaf chunks (`context` + text). It needs no new dependency, and a query takes under 5 ms on
  1.5k chunks. Tokens are Unicode words plus the whole Devanagari and Kannada blocks, because
  Python's `\w` drops Indic vowel signs (a test caught "तलाक" being split). English function
  words are dropped; legal modal words ("shall", "may", "not") are kept.
- **Fusion:** reciprocal rank fusion (k = 60) over every ranking: dense and BM25, for each
  query variant. `alt_queries` is there for Phase 5 (the English translation of a Hindi or
  Kannada question).
- **Reranking:** `CrossEncoderReranker` (bge-reranker-v2-m3, fp16) over the fused top 30.
  There are two strategies: `replace` (the cross-encoder's order) and `fuse` (RRF of the
  first-stage and cross-encoder orders).
- **Defaults:** `retrieval_mode=hybrid`, `rerank_enabled=false`, `rerank_strategy=fuse`.

## Evidence (`python -m scripts.eval_retrieval`, 20 English gold queries)

| config (k = 6) | hit | doc-hit | recall | MRR |
|---|---|---|---|---|
| dense (Phase 3) | 0.75 | 1.00 | 0.70 | 0.617 |
| bm25 | 0.75 | 1.00 | 0.72 | 0.527 |
| **hybrid** | **0.85** | **1.00** | **0.82** | 0.639 |
| dense + rerank (replace) | 0.85 | 0.95 | 0.82 | 0.620 |
| hybrid + rerank (replace) | 0.80 | 0.90 | 0.78 | 0.645 |
| hybrid + rerank (fuse) | 0.85 | 1.00 | 0.82 | 0.631 |

At k = 10, hybrid + fuse reaches 0.90 hit and 0.88 recall, against 0.85 and 0.82 for hybrid.

With `replace`, the cross-encoder ranks g04 perfectly but drops the statute clauses for g11
(HMA s.24) and g12 (s.25) below judgment paragraphs about the same topic. `fuse` avoids that.

The remaining misses (g16, g18, g19) retrieve the right judgment but a neighbouring chunk.
That is a question of how fine-grained the gold set is, not a retrieval failure.

## Consequences

- Reranking is off because it showed no gain at k = 6 on 20 queries. It also costs about
  1.1 GB of VRAM and some latency, on an 8 GB GPU shared with the LLM, ASR and TTS. Turn it
  on with `LEGALAI_RERANK_ENABLED=true`. Re-evaluate once the gold set is larger (Phase 13).
- 20 queries is too few to separate configs within about ±0.05. Treat these results as
  directional.
