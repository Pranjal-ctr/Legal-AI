# ADR 0010 — Phase 12: abuse protection, security headers, privacy-safe logging

Date: 2026-11-02 · Status: accepted

## Context

Every answer uses 10–20 s of a single local GPU, and ASR/TTS use the CPU. The questions are
highly sensitive (domestic violence, divorce, religion). Phase 8 already encrypted stored
sessions. What remained was protecting compute, response headers and the logs.

## Decision

1. **In-process sliding-window rate limiter** (`core/security.RateLimiter`), applied as a FastAPI
   dependency to `/chat`, `/chat/stream` (bucket `chat`, 12/min) and `/asr`, `/tts` (bucket
   `speech`, 40/min, because the UI requests TTS once per sentence). Key = client IP.
   `X-Forwarded-For` is honoured only with `LEGALAI_TRUST_PROXY_HEADERS`. The number of keys is
   capped at 10k (LRU), so the limiter's own memory stays bounded. It returns 429 with `Retry-After`.
   - Rejected: `slowapi`/Redis. That adds a dependency (and a service) for a single-process
     prototype. The dependency boundary makes a later swap local.
2. **Body size limit in the middleware** from `Content-Length` (256 KB JSON; the ASR upload limit +
   64 KB). This rejects oversized requests before parsing. The ASR endpoint still enforces its
   own limit on the actual bytes read, which covers chunked uploads.
3. **Security headers on every response.** A strict CSP applies in production only, because
   Swagger UI at `/docs` (dev only) loads from a CDN.
4. **Logging:** health/ready polling is logged at debug level. LLM parse failures log the
   exception type only (`log_safe_error`), because pydantic/JSON errors echo model output
   derived from the user's question.

## Consequences

- Limits are per process and reset on restart. This is documented in `docs/security.md`.
- 429 responses surface in the UI as the server's plain-language message.
- The setuptools advisory is accepted until torch relaxes `setuptools<82`.
