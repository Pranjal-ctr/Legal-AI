# ADR 0012 — Gemini API as an optional LLM provider

Date: 2026-11-02 · Status: accepted

## Context

The LLM so far has been `gemma4:e4b` served by a local Ollama instance. It fills the 8 GB laptop
GPU together with the embedder and reranker, and a warm answer takes 10–20 s. The user obtained
a Google Gemini API key on the free tier and asked to switch to it.

One Gemini API key covers every model. The model is named in each request
(`POST /v1beta/models/{model}:generateContent`), so the model choice is configuration.

Free-tier limits per model, as shown in the user's AI Studio console on 2026-11-02:

| Model | RPM | TPM | RPD |
|---|---|---|---|
| Gemini 3.5 Flash Lite / 3.1 Flash Lite | 15 | 250K | 500 |
| Gemma 4 31B / 26B | 30 | 16K | 14.4K |
| Gemini 3 / 3.6 / 3.8 Flash, 2.5 Flash | 5 | 250K | 20 |

A chat turn makes 3–7 LLM calls: understanding, 1–2 evidence checks, the answer, an optional
regeneration for an uncited answer, and for hi/kn a question and an answer translation. Daily
requests (RPD) are therefore the binding limit. Models with 20 RPD allow about 4 turns a day.

## Decision

- New `app/providers/gemini.py` → `GeminiLLM`, which implements the existing `LLMProvider`
  protocol. It uses plain `httpx` (already a core dependency), so no SDK is added.
- `LEGALAI_LLM_PROVIDER=ollama|gemini`. Ollama remains the default. `gemini` requires
  `LEGALAI_GEMINI_API_KEY`, and settings validation fails fast without it.
- Default model: `gemini-3.5-flash-lite`, the newest model with 500 RPD. Optional
  `LEGALAI_GEMINI_LIGHT_MODEL` sends the short calls (understanding, evidence check, question
  translation) to another model, e.g. Gemma 4 31B with 14.4K RPD. The answer and its
  translation stay on the main model. `Orchestrator` and `LLMTranslator` take an optional
  `light_llm`, which defaults to the main LLM, so Ollama behaviour is unchanged.
- Structured output: `responseMimeType: application/json` + `responseJsonSchema` (the same
  pydantic JSON schemas Ollama receives). `thinkingConfig.thinkingLevel` defaults to
  `minimal`, because grounded extraction does not need long reasoning. `maxOutputTokens` gets
  512 tokens of headroom, because thinking tokens count against it.
- **Compat mode.** Gemma models on the API reject system instructions and JSON mode. For
  `gemma*` models, and for any model that answers HTTP 400 to the full request, the system
  prompt is folded into the user turn and the schema is stated in the prompt. Code fences
  around JSON are stripped. Downstream JSON parsing already falls back safely on bad JSON.
- **Rate limits.** A per-minute 429 is retried up to twice after the server's `retryDelay`,
  if that is ≤ `LEGALAI_GEMINI_MAX_RETRY_WAIT_S` (20 s). A used-up daily quota (`*PerDay*`
  quota id) fails at once with "resets at midnight Pacific time". 5xx responses are retried
  twice after 2 s. Every failure is an `LLMError`, which the API already maps to 503.
- **Warm-up.** No LLM ping at startup for Gemini (`Orchestrator(warmup_llm=False)`). It would
  only spend daily quota. The embedder and reranker still warm up.
- **Secrets.** The key is sent in the `x-goog-api-key` header, never in the URL, and never
  logged. Connection errors log only the exception type.

## Consequences

- **Privacy.** With `gemini`, questions, retrieved passages and answers are sent to Google.
  On the free tier Google may use them to improve its products. This contradicts the
  local-only stance in `docs/security.md` for real users. `ollama` remains the privacy-preserving
  default, and `scripts/start.ps1` prints which provider is in use.
- Capacity on the free tier: ~70–150 chat turns a day on Flash Lite alone, more with the light
  model split. A full `eval_e2e` run (65 queries) uses most of one day's Flash Lite quota.
- The GPU no longer needs the LLM, so ASR could move back to the GPU later (not done here).
- Model IDs must match what the API lists (`GET /v1beta/models`). An unknown ID fails with
  "model not found (check LEGALAI_GEMINI_MODEL)".
