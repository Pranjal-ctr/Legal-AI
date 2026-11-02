# ADR 0005 — Phase 5 multilingual: script detection, LLM query translation, fused reranking on

- **Status:** Accepted (Phase 5, 2026-11-01)

## Context

Users ask in English, Hindi (Devanagari or romanized "Hinglish") or Kannada. The corpus and the
citations are English and canonical. The architecture (Approach C) plans native-language dense
retrieval, plus an English query from IndicTrans2 for lexical search, plus an answer generated
in the user's language with a reviewed glossary.

## Decision

- **Language detection** (`app/nlp/language.py`) is deterministic. It counts Devanagari,
  Kannada and Latin characters, and treats Latin text as romanized Hindi when at least two
  distinct common Hindi words make up at least 25% of the words. The API's optional `language`
  field overrides detection.
- **Translation** (`TranslationProvider`; `LLMTranslator`) uses the local LLM (gemma4:e4b) at
  temperature 0, with glossary hints. **This deviates from the architecture's IndicTrans2.**
  IndicTrans2 means a second large stack (about 1B parameters plus IndicTransToolkit) on an
  8 GB GPU that is already shared. The LLM's translations of the 40 draft queries were faithful
  (see `reports/retrieval_eval_*_translated.json`) and took about 0.5–1 s each. IndicTrans2 can
  implement the same protocol later if Phase 13 shows translation errors.
- **Retrieval** uses the original question plus its English translation as `alt_queries`.
  Dense and BM25 rankings for both are fused with RRF. The cross-encoder compares passages with
  the English query.
- **Generation:** the system prompt's language rule asks for the answer in the user's language
  and script, with quotations left untranslated. `app/nlp/legal_glossary.json` (29 terms,
  **draft, needs native-speaker review**) supplies the target-language terms. Messages such as
  "no evidence" are localised.
- **Reranking is now on by default** (`rerank_enabled=true`, `fuse`). This reverses the
  Phase 4 default because of the Hindi and Kannada results below.

## Evidence (20 hi + 20 kn draft-translated gold queries, k = 6)

| config | hi hit / doc-hit / recall | kn hit / doc-hit / recall |
|---|---|---|
| dense, native query only | 0.65 / 0.95 / 0.65 | 0.70 / 0.95 / 0.68 |
| hybrid, native query only | 0.70 / 0.95 / 0.70 | 0.75 / 0.95 / 0.72 |
| hybrid + translation | 0.80 / 0.95 / 0.78 | 0.85 / 0.95 / 0.80 |
| **hybrid + translation + rerank (fuse)** | **0.90 / 1.00 / 0.88** | **0.90 / 1.00 / 0.88** |

The English result is unchanged by reranking (0.85 / 1.00 / 0.82).

Live test: VRAM was about 7.7 GB with bge-m3, the reranker and gemma4 all on the GPU.
Latency was about 3–4 s for retrieval and 7–12 s for generation in Hindi or Kannada.

## Known issue

gemma4:e4b sometimes **translates quotations** despite the instruction, so a quoted span is not
verbatim source text. Phase 7 adds a deterministic quote check: a quoted span not found in the
cited English source loses its quotation marks, so it is never presented as a quote.

## Consequences

- The Hindi and Kannada gold queries and the glossary are drafts and need native-speaker review
  before they count as research results.
- Romanized Kannada is not detected; it is treated as English.
