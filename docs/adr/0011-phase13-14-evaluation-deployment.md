# ADR 0011 — Phases 13–14: legal-term query expansion, end-to-end evaluation, single-origin serving

Date: 2026-11-02 · Status: accepted

## 1. Legal-term query expansion (Phase 13 finding)

**Problem.** Lay questions about HMA s.24 never retrieved it. "Can I get maintenance while my
divorce case is pending?" and "interim maintenance during divorce case" put s.24 at rank
none/18 in the top 20. The statute says "maintenance *pendente lite*", "expenses of the
proceeding" and "no independent income sufficient for her or his support". These share almost
no words with the lay phrasing, while judgment paragraphs that use the lay words fill the top 6.
Stating the question in legal vocabulary ("maintenance pendente lite under the Hindu Marriage
Act") put s.24 at rank 1.

**Decision.** The understanding step, which already makes one JSON LLM call, also returns
`legal_terms`: up to 3 phrases in statutory vocabulary, with no section numbers or case names.
They join retrieval as an additional first-stage query and are appended to the cross-encoder
query: `"<english question> (<terms>)"`. Measured on the two failing phrasings, s.24 moved to
rank 1 with no change for questions that already used legal terms (age of marriage, cruelty).
There is no extra LLM call: ~10–20 more output tokens.

**Safety.** The terms only steer search. The answer is still generated only from retrieved
text and validated (citations, verbatim quotes). A wrong term can at worst retrieve less
relevant passages, which the assessor and the round-2 retrieval already handle.

**Rejected.** A hand-written lay→legal synonym table: auditable but brittle, English-only, and
it would need curating for every concept. It can be revisited if the LLM terms prove unstable.

**Tracking.** `data/evaluation/gold_queries_lay.jsonl`: 5 plain-language phrasings of statute
questions (s.24 ×2, s.9, s.25, s.13B) with verbatim evidence, checked by
`tests/integration/test_ingested_corpus.py`.

## 2. End-to-end evaluation

`scripts/eval_e2e.py` runs every gold query (20 en + 40 hi/kn + 5 lay) through the real
orchestrator with automatic language detection. Clarifications are auto-answered with
`religion=hindu`, because every gold query concerns the HMA. Metrics (`app/agents/evaluation.py`)
are computed, not judged by an LLM:

- citation hit: a cited source is the expected chunk or its parent section;
- evidence cited: a cited source contains the gold evidence verbatim;
- quote verification and translation marker checks: from the validator;
- latency p50/p95 and per-step medians.

An LLM-as-judge was rejected for now. With a 4B local model as the judge, its scores would be
less trustworthy than these deterministic proxies. Answer faithfulness needs human review
(see `docs/evaluation.md`).

## 3. Single-origin serving (Phase 14)

FastAPI serves `frontend/dist` with an SPA fallback after the API routes (`core/frontend.py`).
Unknown `/api/*` paths stay JSON 404s. Hashed `assets/` are cached as immutable and
`index.html` is `no-cache`. One origin means:

- no CORS in deployment;
- the production CSP `'self'` covers the UI;
- the microphone works on localhost.

`scripts/start.ps1` is the one-command start. `Dockerfile` + `compose.yaml` (with Ollama) exist
but were not built on the reference machine (see `docs/deployment.md`).
