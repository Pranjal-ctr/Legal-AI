# Kanoon AI — Architecture (Phase 0 design, condensed)

Multilingual (English / Hindi / Kannada) family-law **information and decision-support** system.
Not a lawyer; not legal advice.

## Guiding principles

1. **Deterministic pipeline first; agents only where they earn their place.** The orchestrator is an
   explicit state machine. LLMs: query rewriting, entity-extraction fallback, evidence-grounded
   reasoning/generation, bounded retrieval planning (≤ 2 rounds).
2. **Applicability gating.** Which law applies depends on religion / marriage type (HMA vs SMA vs
   Indian Divorce Act vs Muslim personal law). Secular laws (PWDVA, BNSS §144 maintenance, Dowry
   Prohibition Act) apply to all. Missing applicability facts → ask a clarifying question.
3. **Temporal validity.** BNS/BNSS/BSA replaced IPC/CrPC/Evidence Act on 2024-07-01. Chunks carry
   `effective_from` / `effective_to`; an old→new section mapping table resolves "498A", "125 CrPC".
4. **English authoritative text is canonical.** Citations point to official text; Hindi/Kannada are
   used for understanding and explanation, never as a re-worded source.
5. **Provider abstraction.** `LLMProvider`, `EmbeddingProvider`, `RerankerProvider`, `ASRProvider`,
   `TTSProvider`, `TranslationProvider`, selected by environment configuration.

## Request flow

```text
Input (text | voice→ASRRouter) → LanguageDetector
→ load ConversationState → SafetyGate.pre → QueryUnderstanding → Clarification?
→ QueryRewriter (standalone + EN query) → RetrievalPlanner
→ Hybrid retrieval (bge-m3 dense + BM25) → RRF → reranker (bge-reranker-v2-m3) → EvidenceValidator
→ LegalReasoner/ResponseGenerator (evidence-only, structured JSON) → CitationValidator
→ SafetyGate.post → persist → response (+ optional TTS)
```

## Multilingual strategy (Approach C — hybrid)

Native-language dense retrieval (bge-m3) + EN-translated query (IndicTrans2) for lexical search,
fused. Reasoning over English canonical evidence; answer generated directly in the user's language
with a reviewed legal glossary. Original-language quotes preserved. To be validated in Phase 5.

## Chunking

Hierarchical parent–child: child = subsection/clause/proviso/explanation (retrieval unit), parent =
full section (LLM context). Stable IDs, e.g. `hma1955:s13:ss1:cl(ia)`. Contextual header prepended
before embedding. Judgments: numbered paragraphs + headnote.

## Data stores

- **PostgreSQL** — source of truth (users, sessions, messages [encrypted], conversation_state,
  documents, chunks, section_mappings, citations, feedback, audit_log, eval_runs).
- **Qdrant** — vectors keyed by `chunk_id`.
- **Redis** — hot conversation state, rate limits, caches.

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 0 | System design | Done |
| 1 | Skeleton: FastAPI `/api/v1/health`, React/Vite/Tailwind, config, logging, tests, CI | Done |
| 2 | Ingestion (start with HMA 1955 + 20 gold queries) | — |
| 3 | Baseline RAG + minimal chat UI | — |
| 4–15 | Hybrid retrieval, multilingual, understanding, agentic RAG, memory, ASR, TTS, UI, security, evaluation, deployment, research write-up | — |

Architectural changes are recorded in `docs/adr/`.
