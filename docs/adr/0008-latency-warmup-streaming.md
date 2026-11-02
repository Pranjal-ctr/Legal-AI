# ADR 0008: Latency, startup warm-up, live progress streaming, and a resident LLM

- **Status:** Accepted (2026-11-02; approved under "fully usable")

## Context

The first question after a server start waited about 55 s (lazy model loading), and every
answer took 12–20 s with no feedback. A user cannot tell a slow answer from a hung one.

## Decision

- **Warm-up at startup** (`LEGALAI_WARMUP_ON_STARTUP`, skipped in `test`): a background task
  builds the orchestrator, runs one retrieval (loads bge-m3 and the reranker), and makes a
  2-token LLM call. Then it loads the ASR model and the three TTS voices. Failures are logged, and
  requests still work (they report setup errors as 503). Measured: everything is ready about
  2 minutes after start, without blocking the API.
- **Resident LLM:** Ollama `keep_alive` is `30m` (`LEGALAI_LLM_KEEP_ALIVE`), replacing the 5-minute
  default, so the model does not unload between questions.
- **Live progress:** `POST /api/v1/chat/stream` (Server-Sent Events) sends a `step` event as each
  orchestrator stage starts, then the `result` (the same ChatResponse as `/chat`) or an `error`.
  The UI shows "Understanding… / Searching… / Checking the evidence… / Writing and verifying… /
  Translating…". Token streaming of the answer is **not** used: the answer is validated (citations,
  verbatim quotes) and then translated, so partial text would show unverified content.
  Client disconnect cancels the work.
- Not done: a conditional assessor (skip it when the reranker is confident) needs evaluation
  data first (Phase 13). Removing the separate query translation was not worth its ~0.5 s.

## Consequences

Warm English answers take 10–11 s, including a second retrieval round when needed (measured
2026-11-02). One outlier of 38 s happened on the first long prompt after warm-up (buffer
allocation). Progress is visible within 0.2 s of asking.
