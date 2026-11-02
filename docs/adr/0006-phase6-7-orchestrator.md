# ADR 0006: Phases 6–7, query understanding, applicability gate, and an English-first agentic orchestrator

- **Status:** Accepted (Phases 6–7, 2026-11-01)

## Context

Phase 5 generated answers directly in Hindi or Kannada. gemma4:e4b translated quotations of the
law despite the instructions, and the quality of its answers was worse in Indic languages than
in English. The architecture also requires (a) applicability gating, because the Hindu Marriage
Act governs only some marriages; (b) at most two retrieval rounds; (c) LLM agents only where they
earn their cost; and (d) a deterministic, traceable control flow.

The user proposed this pipeline: whatever the input language (text or, later, voice), retrieve
and answer in English, then translate the answer into the user's language.

## Decision

`app/agents/orchestrator.py` runs a deterministic state machine. `RagService` is removed.

```text
LANGUAGE (script detection, or the explicit `language` field)
→ translate_query (non-English only; the English query feeds lexical search and the reranker)
→ UNDERSTAND (LLM JSON schema: in_scope, topic, religion, marriage_type, emergency,
              standalone_question; regex rules override for explicit religion statements and
              Special Marriage Act mentions; names are never used to infer religion)
→ OUT_OF_SCOPE (in_scope=false and not an emergency) → fixed localised refusal, no retrieval
→ GATE (applicability.assess):
     personal-law topic + religion unknown           → CLARIFY (localised buttons)
     muslim/christian/parsi/jewish, SMA, nikah, ...   → not_applicable: HMA statute evidence is
                                                        dropped, notice shown, generator told
     user chose "prefer not to say"                   → answer with a qualifying notice
     secular topics (domestic violence, dowry, ...)   → not gated
→ RETRIEVE round 1 (hybrid + fused reranker, original + English query)
→ ASSESS (LLM JSON: relevant source numbers, sufficient?, follow-up query)
→ RETRIEVE round 2 only if insufficient (max_rounds = 2), merged, renumbered
→ GENERATE in English (an uncited answer is regenerated once)
→ VALIDATE: invalid [n] removed; quotations must be verbatim source text, or their quote marks
            are removed (ellipsis fragments are checked one by one)
→ TRANSLATE the answer (non-English): [n] markers must survive (one retry, then English
            fallback with a notice); translated quotations are restored as
            "<English law text>" (<translation>)
→ RESPOND: answer, answer_en, notices (emergency 112 / 181 first), clarification, analysis,
           validation, trace (per-step ms)
```

- **English-first generation** keeps citations and quotations canonical (the English official
  text is canonical, per the architecture). Translation becomes a separate, checkable step. The
  UI can show the English original.
- **Applicability rules are code, not prompts.** The LLM only extracts facts; `applicability.py`
  decides. User-supplied facts (`ChatRequest.facts`, set by the clarification buttons) are merged
  before the gate and win over the extraction.
- **The assessor** is an LLM step. It can be switched off (`LEGALAI_AGENT_ASSESS_EVIDENCE`).
- Localised fixed texts (clarification, notices, refusal) are in `applicability.py`. They are
  **drafts that need native-speaker review**, like the glossary.

## Consequences

- Latency (warm, RTX 4060 8 GB): English ~12 s, Hindi ~15 s, Kannada ~18 s, ~20 s with two
  rounds; cold start ~55 s. Optimisations (streaming, dropping the duplicate query translation,
  a conditional assessor, warm-up) have been proposed and are awaiting approval.
- An LLM call is spent on understanding even for simple questions. The rule-based
  `fallback_analysis` keeps the system working if JSON parsing fails.
- Corpus limit: only HMA 1955 is ingested, so not_applicable questions are answered from
  judgments with a notice. They do not get the correct statute (SMA, Muslim personal law), which
  is not in the corpus yet.
- Tests: `tests/unit/rag/test_understanding.py`, `test_orchestrator.py` (every state-machine
  path, the validators, quote restoration), `tests/integration/test_chat.py`.
