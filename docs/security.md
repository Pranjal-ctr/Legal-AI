# Security and privacy (Phase 12)

Kanoon AI is a research prototype. It is meant for a single machine or a small, trusted
deployment, not the open internet at scale. This document covers what it protects, how it does
so, and what it deliberately leaves out.

## Assets

| Asset | Why it matters |
|---|---|
| User questions, answers and voice recordings | Family-law questions reveal abuse, divorce, custody and religion. This is highly sensitive personal data. |
| Session profile (religion, marriage type) | Sensitive personal data (religious belief). |
| Feedback ratings | Linked to a session. |
| `LEGALAI_SESSION_KEY` / `data/sessions/secret.key` | Anyone with the key can decrypt every stored session. |
| Local compute (GPU LLM, CPU ASR/TTS) | One answer takes 10–20 s of GPU time, which makes it easy to exhaust. |
| Answer integrity | A wrong citation or a misquoted provision misleads a vulnerable user. |

## Threats and controls

| Threat | Control | Where |
|---|---|---|
| Sensitive text in logs | Access logs record path, status and duration only, never bodies or query strings. App logs record counts, languages, topics and timings. LLM parse failures log only the exception type, because pydantic/JSON errors echo the model output, which paraphrases the question. ASR logs the language, not the transcript. | `core/middleware.py`, `core/security.log_safe_error` |
| Stored conversations read from disk | Message text and the profile are Fernet-encrypted (AES-128-CBC + HMAC) in SQLite. Sessions expire after 30 days (TTL purge). "New conversation" deletes the session; feedback cascades with it. A key is required in production (startup fails without one). | `memory/` (ADR 0007) |
| Voice recordings retained | Uploads are spooled to `LEGALAI_TEMP_DIR`, decoded in memory and never stored. TTS audio is not cached on disk and is served `Cache-Control: private`. | `api/v1/endpoints/speech.py` |
| Compute exhaustion / DoS | Per-client sliding-window limits return 429 with `Retry-After`: chat 12/min, speech 40/min (TTS is called once per sentence). Request bodies are capped from `Content-Length` before parsing (256 KB JSON; ASR = upload limit + 64 KB). Audio is capped at 60 s, TTS text at 1,200 chars and the question at the schema limit. The LLM call has a timeout, and a disconnected stream cancels its work. | `core/security.py`, schemas, settings |
| IP spoofing to dodge limits | `X-Forwarded-For` is ignored unless `LEGALAI_TRUST_PROXY_HEADERS=true`. Enable it only behind a proxy that overwrites the header. | `core/security.client_key` |
| Clickjacking, MIME sniffing, referrer leaks | Every response carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cross-Origin-Opener-Policy: same-origin`, and a `Permissions-Policy` limiting the microphone to self (camera, geolocation and payment are off). | `core/middleware.py` |
| XSS | React escapes all model output (no `dangerouslySetInnerHTML`). Production adds a strict CSP: scripts and connections to `'self'`, `frame-ancestors 'none'`, no objects. Inline styles are allowed for Tailwind/React style props. | `core/security.CONTENT_SECURITY_POLICY` |
| Session hijack / enumeration | Session ids are 128-bit random (`secrets.token_hex(16)`), validated as `^[0-9a-f]{32}$`. The UI does not keep them in persistent storage. | `memory/store.py`, `schemas/chat.py` |
| Cross-origin calls | CORS allow-list from `LEGALAI_CORS_ORIGINS` (default: the dev UI origin only). | `main.py` |
| API surface discovery | `/docs` and `/openapi.json` are disabled in production. | `main.py` |
| Error detail leaks | Unhandled errors return a generic problem+json 500 with a request id. The stack trace stays in the server log. | `core/middleware.py` |
| Prompt injection via the question | The LLM has no tools and no side effects. It only writes text. Citations are checked against retrieved sources, quotes must be verbatim corpus text (otherwise they are removed), and the applicability gate is deterministic code. An injected instruction can at worst produce an ungrounded answer, and the validator flags that. | `agents/validation.py`, ADR 0006 |
| Fabricated legal content | English-first generation from retrieved evidence only. `[n]` markers must map to sources, and quotes are verified against the canonical text. The UI always says "information, not legal advice" and shows helplines. | `rag/prompt.py`, `agents/` |
| Supply chain | Locked dependencies (`uv.lock`, `package-lock.json`). Models load offline from `models/` after the first download. Audits: `uvx pip-audit` and `npm audit` (see below). | — |

## Dependency audit (2026-11-02)

- `npm audit`: 1 high-severity issue (undici, via jsdom, dev/test only) was fixed with `npm audit fix`. 0 remain.
- `pip-audit` over the locked `dev, ingest, embed, speech` set found **setuptools 81.0.0** (PYSEC-2026-3447,
  GHSA-xmj3-9gf7-h52w). It cannot be upgraded because torch 2.11 requires `setuptools<82`.
  **Accepted:** setuptools is a packaging/build tool pulled in by torch, and no request path
  calls it. Re-check when torch relaxes the pin. torch (`+cu128` wheel, not on PyPI) could not
  be audited by pip-audit.

Re-run:

```powershell
uv export --frozen --no-hashes --extra dev --extra ingest --extra embed --extra speech --no-emit-project -o .tmp/req.txt
uvx pip-audit -r .tmp/req.txt --no-deps --disable-pip
cd frontend; npm audit
```

## Not in scope (known limitations)

- **No authentication.** Anyone who can reach the server can use it. Deploy it on localhost or a
  private network, or put it behind an authenticating reverse proxy.
- **In-memory rate limits:** these are per process and reset on restart. A multi-worker or
  multi-host deployment needs a shared store (e.g. Redis).
- **TLS is not terminated by the app.** Use a reverse proxy (Caddy, nginx) for HTTPS. Browsers
  allow microphone access only on HTTPS or localhost.
- **Encryption key on the same disk** in development (`data/sessions/secret.key`). Production
  must supply `LEGALAI_SESSION_KEY` from a secret store.
- **Ollama** listens on localhost with no auth. Do not expose port 11434.
- **Gemini provider (ADR 0012).** With `LEGALAI_LLM_PROVIDER=gemini`, questions, retrieved
  passages and answers are sent to Google. On the free tier, Google may use them to improve
  its products. Use it for development and evaluation, not for real users' questions. Keep
  `LEGALAI_GEMINI_API_KEY` in `.env` or a secret store. It is sent only in a request header
  and is never logged.
- **Model licences:** MMS-TTS is CC-BY-NC 4.0 (non-commercial only).
