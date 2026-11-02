# CLAUDE.md — Kanoon AI (LegalAi) project context

> **Keep this file current.** Update it after every change: phase status, new modules, commands,
> decisions, and the change log at the bottom.

## What this is

Research prototype: multilingual (English / Hindi / Kannada) agentic RAG system giving
source-grounded **information** (not legal advice) about Indian family law.
Stack: FastAPI (Python 3.11+, uv) + React 19 / TypeScript / Vite / Tailwind 4.
Repo: https://github.com/Pranjal-ctr/Legal-AI · Design: `docs/architecture.md` · ADRs: `docs/adr/`.

## Working rules (from the user — mandatory)

- **Phase-gated.** Build strictly phase by phase (0–15). Write no code for a phase until the user
  says `START PHASE N`. At the start of a phase state: Goal / Architecture / Files / Dependencies /
  Steps / Testing / Acceptance criteria.
- Each phase must work and be tested before the next. Give complete files; explain any
  architecture change (and record it as an ADR).
- **Never fabricate legal data, sections, or citations.**
- On errors: root cause → file → fix → test command → expected success. Never rewrite the project.
- **Commits: no Claude attribution** — no `Co-Authored-By: Claude`, no "Generated with Claude Code".
  Author is the user only. Commit/push only when asked.

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 0 | System design | Done (2026-10-07) |
| 1 | Skeleton: FastAPI `/api/v1/health`, React/Vite/Tailwind, config, logging, tests, CI | Done (commit `aaac1fa`) |
| 2 | Ingestion: HMA 1955 + 48 judgments → hierarchical chunks + 20 gold queries (ADR 0002) | Done (commit `ff4cafd`) |
| 3 | Baseline RAG + chat UI: bge-m3 → embedded Qdrant → gemma4:e4b (Ollama), `POST /api/v1/chat` (ADR 0003) | Done 2026-11-01 (branch `phase-3-rag`, uncommitted) |
| 4 | Hybrid retrieval: BM25 + RRF + bge-reranker-v2-m3 (`fuse`) (ADR 0004) | Done 2026-11-01 (uncommitted) |
| 5 | Multilingual: script detection, LLM query translation, draft glossary, 40 hi/kn gold (ADR 0005) | Done 2026-11-01 (uncommitted) |
| 6–7 | Query understanding, applicability gate, clarification, agentic orchestrator (≤2 rounds, assessor), English-first answer → verify → translate (ADR 0006) | Done 2026-11-01 (uncommitted) |
| 8 | Memory: encrypted SQLite sessions, history → understanding, remembered clarification facts, delete (ADR 0007) | Done 2026-11-01 (uncommitted) |
| 8b | Latency: startup warm-up, Ollama keep_alive, SSE progress `/chat/stream` (ADR 0008) | Done 2026-11-02 (uncommitted) |
| 9 | ASR: faster-whisper large-v3-turbo CPU int8, single-pass detect+decode, ambiguity re-decode, `/asr`, mic button (ADR 0009) | Done 2026-11-02 (uncommitted) |
| 10 | TTS: MMS-TTS hin/kan/eng CPU, speech_text cleaning, `/tts`, Listen button (ADR 0009) | Done 2026-11-02 (uncommitted) |
| 11 | UI: welcome + examples + helplines, en/hi/kn UI strings (draft), status pill via `/ready`, feedback (`/feedback`, encrypted, erased with session), copy, auto-scroll | Done 2026-11-02 (uncommitted) |
| 12 | Security: per-IP rate limits (429), body size limits (413), security headers + prod CSP, privacy-safe logs, dependency audit, threat model `docs/security.md` (ADR 0010) | Done 2026-11-02 (uncommitted) |
| 13 | Evaluation: `scripts/eval_e2e.py` (65 gold queries through the real orchestrator), lay gold set, legal-term query expansion fixing the HMA s.24 gap (ADR 0011) | **In progress** (full run going; results → `docs/evaluation.md` still to write) |
| 14 | Deployment: FastAPI serves `frontend/dist` (single origin), `scripts/start.ps1`, Dockerfile + compose.yaml, `docs/deployment.md` (ADR 0011) | **Mostly built** (start.ps1 live test pending; Docker image NOT built: engine off, C: full) |
| 15 | Research write-up `docs/research.md`, final README | — (user authorised ALL remaining phases, 2026-11-02) |

## Layout (ADR 0001: single Python project at repo root)

```text
backend/app/          importable package `app` (hatchling packages = ["backend/app"])
  main.py             create_app() factory; CORS + RequestContextMiddleware (X-Request-ID)
  __main__.py         `python -m app` → uvicorn
  core/config.py      Settings (pydantic-settings, prefix LEGALAI_, .env), load_settings()
  core/logging.py     structlog config (console or JSON)
  core/middleware.py  request id, access logging (health/ready at debug), body size limit, security headers
  core/security.py    RateLimiter + rate_limit(bucket) dependency, client_key, SECURITY_HEADERS/CSP, log_safe_error
  core/frontend.py    mount_frontend(): built UI at / with SPA fallback (after API routes; /api/* stays 404 JSON)
  core/deps.py        FastAPI dependencies (settings from app.state)
  api/v1/router.py    api_router; endpoints/health.py → GET /api/v1/health
  schemas/health.py   HealthResponse
  ingestion/          Phase 2 (needs `ingest` extra = pdfplumber)
    models.py         Document, Chunk (kinds: section|provision|judgment_summary|judgment_paragraph)
    pdf.py            pdfplumber + dedupe_chars, text cache data/processed/text_cache/<sha256>.json
    statute.py        ActSpec (HMA_1955); sections → provision chunks; amendment footnotes per section
    judgment.py       header/footer strip, metadata, S.C.R. issue/headnotes, numbered-para chain
    corpus.py         discover data/family_law_dataset, collapse byte-identical duplicates
    pipeline.py       ingest() + write_outputs(); STATUTES registry; ORIGINS
    text.py           clean/join lines, parse_date, split_long, ACT_PATTERNS → statutes_cited
  providers/          hf.py (offline local_snapshot), embedding.py (bge-m3), reranker.py
                      (CrossEncoderReranker), llm.py (OllamaLLM: json_schema, max_tokens, think off),
                      gemini.py (GeminiLLM, ADR 0012: header key, responseJsonSchema, gemma compat,
                      429 retryDelay / daily-quota fail-fast),
                      translation.py (LLMTranslator: query→en, answer en→hi/kn keeping [n])
  retrieval/          bm25.py (Indic-aware tokenizer), corpus.py (Corpus.load, leaf units, fingerprint),
                      store.py (VectorStore over Qdrant, uuid5(chunk_id) ids), index.py
                      (build_index, Retriever: dense|bm25|hybrid, rrf_fuse, rerank replace|fuse,
                      alt_queries), evaluation.py
  nlp/                language.py (detect_language, Hinglish), glossary.py + legal_glossary.json (draft)
  rag/                prompt.py (build_system_prompt, assemble_evidence provision→section,
                      check_citations), factory.py (build_orchestrator from Settings)
  agents/             understanding.py (QueryAnalysis via LLM JSON + religion/SMA regex rules;
                      legal_terms → extra search query + appended to rerank query, ADR 0011),
                      applicability.py (gate + localised clarify/notice texts), validation.py
                      (verbatim quotes, restore_quotes, markers), orchestrator.py (state machine),
                      evaluation.py (E2EResult, score_result, doc_hit, rescore, summarise, percentile)
  providers/asr.py    FasterWhisperASR (own PyAV decode, VAD, one encoder pass, ambiguity re-decode)
  providers/tts.py    MMSTTS (VITS per language, LRU cache); nlp/speech_text.py (speakable clauses)
  api/v1/endpoints/speech.py  POST /api/v1/asr (multipart) and /api/v1/tts (→ audio/wav)
  memory/             crypto.py (Fernet Cipher, load_key), store.py (SessionStore: sqlite3,
                      encrypted payload/facts, TTL purge, history in English)
  api/v1/endpoints/sessions.py  GET/DELETE /api/v1/sessions/{id}
  api/v1/endpoints/chat.py  POST /api/v1/chat {message, language?, facts?, session_id?}; core/deps.py builds the
                      Orchestrator lazily (503 if corpus/index missing, LLMError → 503)
scripts/build_index.py      → data/index/{qdrant/, index_meta.json} (git-ignored)
scripts/eval_retrieval.py   → reports/retrieval_eval*.json (configs, --language hi|kn, --translate)
scripts/make_multilingual_gold.py → data/evaluation/gold_queries_multilingual.jsonl (40 draft)
scripts/eval_e2e.py         → reports/e2e_eval.{json,md} (--limit, --language, --rescore results.json)
scripts/check_gemini.py     lists model IDs for the key + probes configured models (plain + JSON)
scripts/start.ps1           one-command start: ingest/index if missing, build UI, production mode
Dockerfile, compose.yaml    UI build stage + Python/uv app; Ollama service (GPU); app on 127.0.0.1:8000
scripts/ingest.py     `python -m scripts.ingest` → data/processed/{documents,chunks}.jsonl,
                      ingest_report.json, data/manifest.json (committed)
frontend/src/         App.tsx (header + StatusPill), components/{Chat,StatusPill}.tsx, i18n.ts (en/hi/kn UI
                      strings, EXAMPLES), hooks/{useChat (SSE progress, session), useRecorder (mic + VAD auto-stop, ADR 0013),
                      useSpeaker (sentence-pipelined TTS), useReadiness (polls /health + /ready)},
                      services/api.ts, types/api.ts; tests colocated (Vitest)
scripts/              offline CLIs, run as `python -m scripts.<cli>` from repo root
tests/                unit/, integration/ (pytest; pythonpath = backend, .)
data/                 raw/ processed/ family_law_dataset/ (git-ignored), manifest.json,
                      evaluation/gold_queries.jsonl (20 draft queries, chunk ids + verbatim evidence),
                      evaluation/gold_queries_lay.jsonl (5 plain-language statute questions, l01–l05)
models/ reports/      git-ignored caches/outputs
```

## Commands (run from repo root)

```powershell
uv sync --extra dev --extra ingest --extra embed --extra speech   # speech = faster-whisper (+ MMS via transformers)
# uv cache is on D: via [tool.uv] cache-dir; set TMP/TEMP to .tmp for big installs (C: is full)
uv run python -m scripts.ingest   # ~4 min first run (PDF extraction), seconds when cached
uv run python -m scripts.build_index     # ~1 min on GPU; stop the API first (Qdrant file lock)
uv run python -m scripts.eval_retrieval  # k=6 hybrid+fuse: hit 0.85, recall 0.82; hi/kn translated 0.90
uv run python -m scripts.eval_e2e       # end-to-end answers, ~10 s/query + ~2 min model load; stop the API
uv run python -m scripts.check_gemini   # after pasting LEGALAI_GEMINI_API_KEY into .env (--list = IDs only)
uv run python -m app          # backend :8000 (health: /api/v1/health, docs: /docs in dev)
.\scripts\start.ps1          # one command: UI + API on :8000, production mode (-Rebuild, -Dev)
uv run pytest; uv run ruff check .; uv run ruff format .; uv run mypy
cd frontend; npm install; npm run dev   # :5173
npm test; npm run typecheck; npm run build
```

CI (`.github/workflows/ci.yml`): backend installs `.[dev,ingest]` (qdrant-client/httpx are core
deps; no torch: tests use tests/fakes.py — FakeEmbedder, FakeLLM, in-memory Qdrant); ruff check + format --check + mypy (strict) + pytest on
Python 3.12; frontend typecheck + test + build on Node 22.

## Key design decisions (see docs/architecture.md)

- Deterministic state-machine orchestrator; LLM agents only where they earn it (≤ 2 retrieval rounds).
- Applicability gating by religion / marriage type (HMA vs SMA vs Indian Divorce Act vs Muslim
  personal law); secular laws (PWDVA, BNSS §144, Dowry Prohibition Act) apply to all.
- Temporal validity: BNS/BNSS/BSA replaced IPC/CrPC/Evidence Act on 2024-07-01; chunks carry
  `effective_from`/`effective_to`; old→new section mapping table.
- English official text is canonical for citations; hi/kn for understanding/explanation.
- Provider abstractions: LLM, Embedding, Reranker, ASR, TTS, Translation — chosen by env config.
- Chunking: parent (section) / child (subsection, clause, proviso, explanation); stable IDs like
  `hma1955:s13:ss1:cl(ia)`; contextual header prepended before embedding.
- Stores as built: embedded Qdrant (vectors by `chunk_id`) + encrypted SQLite (sessions, feedback).
  PostgreSQL/Redis were the Phase 0 plan and were not built (see docs/architecture.md, "Changes from the Phase 0 design").
- Heavy stacks go in optional dependency groups (e.g. `.[speech]`).

## Source corpus (data/raw — git-ignored, so provenance is recorded here)

| File | Source | Notes |
|---|---|---|
| `data/family_law_dataset/` | 49 judgment PDFs supplied by the user: Supreme Court from Digital S.C.R. (digiscr.sci.gov.in), High Courts from eCourts (judgments.ecourts.gov.in). Per-file sha256 + extracted metadata in `data/manifest.json`. | 48 unique (Dhananjay Rathi, 2026 INSC 360, duplicated across divorce + domestic_violence → one doc, both topics). Kept by user choice though off-topic: Balaji Formalin v. UoI (poisons rules), Sardari Lal v. Bishan Dass (will). `acts and laws/` folder is empty. |
| `data/raw/hma1955.pdf` | Punjab & Haryana High Court mirror of the Legislative Dept. text: https://www.highcourtchd.gov.in/hclscc/subpages/pdf_files/4.pdf (downloaded 2026-10-23) | 13 pages, text-extractable (pypdf). Amendments through Act 6 of 2019 (leprosy ground removed). sha256 `11547fa0…2e3a295a`. India Code (indiacode.nic.in, handle 123456789/1560) is canonical but blocks scripted downloads (403/504). |

## Local environment notes

- C: is nearly full. The uv cache is `.uv-cache/` on D: (git-ignored), and HF model weights live
  in `models/hf` (bge-m3, ~2.2 GB, ONNX files skipped).
- Ollama runs locally with `gemma4:e4b` (also gemma2:9b, mistral). The GPU is an RTX 4060
  Laptop with 8 GB: Ollama + bge models fill it (~7.6 GB), so ASR/TTS run on CPU (16 cores).
- Model weights: `models/hf` (bge-m3, reranker, mms-tts-*), `models/whisper` (large-v3-turbo).
- `.env` sets `LEGALAI_TEMP_DIR=.tmp` (uploads spool to D:). Bash heredocs mangle `\n`/quotes in
  this environment: write patch scripts with the Write tool and run them.

## Conventions

- Python: ruff (line 100, rules E,F,I,B,UP,SIM,ASYNC,S,RUF), mypy strict, type hints everywhere,
  module docstrings, structlog for logging.
- Config only via `Settings`; invalid values fail fast. Never commit `.env`.
- Ingestion never guesses metadata: unfound court/date/citation stay null and are listed in
  `ingest_report.json` (currently 3 HC docs). Source typos (e.g. "imporence", "wher") are kept
  verbatim — canonical text is never "corrected".
- Chunk ids are referenced by gold queries; `tests/integration/test_ingested_corpus.py` fails if
  an id disappears or its evidence text changes.

## Change log

- 2026-10-07 — Phase 0 design; Phase 1 skeleton built.
- 2026-10-22 — Initial commit `aaac1fa` (scaffold, tests, CI, docs).
- 2026-10-23 — Added this CLAUDE.md. Verified: 13 pytest pass, ruff + mypy clean.
- 2026-10-23 — Downloaded official-format HMA 1955 text to `data/raw/hma1955.pdf` (see Source corpus).
  Phase 2 will need `pypdf` (likely as an optional `ingest` extra).
- 2026-10-30 — User added `data/family_law_dataset/` (49 judgments). Phase 2 built: `app/ingestion`
  (pdfplumber instead of pypdf: pypdf splits words, e.g. "prese nted"), `scripts/ingest.py`,
  ADR 0002, `Settings.data_dir`, gold queries, manifest. Output: 49 docs, 1491 chunks (37 sections,
  114 provisions, 1235 judgment paragraphs, 105 summaries). 41 pytest pass; ruff + mypy clean.
- 2026-11-01 — Phase 3 built (ADR 0003): providers (bge-m3, Ollama), retrieval (embedded Qdrant,
  leaf-chunk index with corpus fingerprint), RAG service with citation checks, `POST /api/v1/chat`,
  React chat UI with numbered sources, build_index/eval_retrieval scripts. qdrant-client + httpx
  moved to core deps; `embed` extra for torch. 74 pytest + 8 vitest pass; ruff, mypy, and tsc are
  clean; verified end to end in the browser. Known weakness: g04 (statute clause outranked by
  judgments). Phase 4 targets it.
- 2026-11-01 — Phases 4–7 built (ADRs 0004–0006). Phase 4: BM25 + RRF + reranker (`fuse`),
  hit@6 0.75→0.85. Phase 5: language detection, LLM translation (IndicTrans2 deferred), draft
  glossary, hi/kn gold (translated 0.90 hit). Phases 6–7: `app/agents` orchestrator replaces
  RagService. English-first generation → citation/verbatim-quote validation → translation with
  [n] check and English quote restore. Applicability gate + clarification buttons, emergency
  notice, out-of-scope refusal, ≤2 retrieval rounds with an LLM assessor, per-step trace in the UI.
  144 pytest + 11 vitest pass; live-verified en/hi/kn. Warm latency 12–20 s. Latency
  optimisations proposed and **awaiting user approval**.
- 2026-11-01 — Phase 8 built (ADR 0007): `app/memory` (encrypted SQLite sessions, 30-day TTL),
  `session_id` in chat, GET/DELETE sessions, profile = explicit clarification answers only
  (`fill_facts` precedence: request > question > profile), "New conversation" button deletes the
  session. `cryptography` is an explicit core dep; production requires LEGALAI_SESSION_KEY.
  162 pytest + 12 vitest pass; live multi-turn en→hi verified. Gap noted: HMA s.24 not
  retrieved for "maintenance while case pending" (Phase 13).
- 2026-11-02 — User: "complete it fully usable" → all remaining phases authorised. Latency
  (ADR 0008): startup warm-up, keep_alive 30m, SSE `/chat/stream` with live progress UI (warm answers
  10–11 s). Phase 9 ASR + Phase 10 TTS (ADR 0009): faster-whisper large-v3-turbo on CPU (8–12 s;
  single encoder pass; Kannada fixed by runner-up re-decode), MMS-TTS hin/kan/eng (CC-BY-NC), mic and
  Listen buttons. `speech` extra, python-multipart core dep, `[tool.uv] cache-dir`, LEGALAI_TEMP_DIR.
  185 pytest + 18 vitest pass; live TTS→ASR round trip verified en/hi/kn.
- 2026-11-02 — Phase 11 UI: header status pill (`GET /api/v1/ready`: answers/speech_input/speech_output
  = loading|ready|unavailable|disabled|on_demand, fed by the warm-up), welcome screen with one-click
  examples and helplines (112, 181, NALSA 15100), UI strings follow the language selector (auto: the
  last answer's language), 👍/👎 → `POST /api/v1/feedback` (encrypted `feedback` table, cascades on
  session delete), copy with citations, auto-scroll, compact sticky composer. BackendStatus/useHealth
  removed. 187 pytest + 24 vitest; verified in Chrome (hi clarification → answer → Listen).
- 2026-11-02 — Phase 12 security (ADR 0010, `docs/security.md` threat model): in-memory sliding-window
  rate limits per client IP (chat 12/min on /chat + /chat/stream, speech 40/min on /asr + /tts → 429 +
  Retry-After; X-Forwarded-For only with LEGALAI_TRUST_PROXY_HEADERS), Content-Length body limits (256 KB
  JSON, ASR upload + 64 KB → 413), nosniff/DENY/no-referrer/COOP/Permissions-Policy on all responses,
  strict CSP in production, /health + /ready access logs at debug, LLM parse failures log the exception
  type only. Audit: npm undici (dev) fixed; setuptools 81 advisory accepted (torch pins <82).
  194 pytest + 24 vitest; live-verified headers, 413 and 429.
- 2026-11-02 — Phase 13 (in progress) + Phase 14 (mostly built), ADR 0011:
  - HMA s.24 gap root cause: lay phrasing ("maintenance while case pending", "interim maintenance")
    shares no words with the statute ("pendente lite", "expenses of the proceeding"); s.24 was not in the
    top 20 / rank 18. Fix: QueryAnalysis.legal_terms (same understanding LLM call, ≤3 statutory phrases,
    no section numbers) → extra first-stage query + appended to the reranker query. s.24 now rank 1 for
    both; age-of-marriage / cruelty queries unchanged. New gold set `gold_queries_lay.jsonl` (l01–l05).
  - `app/agents/evaluation.py` + `scripts/eval_e2e.py`: deterministic metrics (citation hit incl. parent
    section, doc-level citation, gold evidence in a cited source, quote verification, translation markers,
    language detection, clarification rate, latency p50/p95, per-step medians). Clarifications are
    auto-answered religion=hindu. No LLM judge (a 4B judge is less trustworthy than these proxies).
    Partial run: first 30 queries ~7–16 s each; misses so far are judgment queries citing the right
    judgment but another paragraph (hence the doc-level metric).
  - Deployment: `core/frontend.py` serves frontend/dist (immutable assets/, no-cache index.html,
    Settings.frontend_dist; tests set it None); `scripts/start.ps1` (temp on D:, Ollama check, ingest +
    index if missing, UI build, production mode with the session key from env/.env or
    data/sessions/secret.key for the process only); Dockerfile (node:22 UI stage, python:3.12-slim + uv
    0.9.16, uid 10001) + compose.yaml (ollama/ollama:0.40.13 with GPU, app on 127.0.0.1:8000) +
    .dockerignore; `docker compose config` validates but the image was NOT built. `docs/deployment.md`
    (measured: models/ 6.2 GB, gemma4:e4b 6.6 GB, GPU ~7.6 GB with embedder + reranker).
  - README: one-command run, speech extra, eval_e2e, security link. 204 pytest; ruff + mypy clean.
  - Remaining: finish e2e run → `--rescore` → `docs/evaluation.md`; live-test start.ps1; Phase 15
    `docs/research.md`; tell the user what still uses C: (npm cache, Ollama models dir).
- 2026-11-02 — Voice mode (frontend only): a spoken question is sent as soon as it is transcribed
  (typed draft prepended; language = selector, else Whisper's detected language) and its answer, or
  clarification question, is read aloud automatically; typed questions stay text-only (Listen button).
  Mic press stops any playback (barge-in). `voice` flag on chat messages, carried through clarification.
  25 vitest + tsc clean. Not yet tried with a real microphone by Claude.
- 2026-11-02 — Gemini API provider (ADR 0012), on user request: `LEGALAI_LLM_PROVIDER=ollama|gemini`
  (Ollama stays the code default; the user's `.env` now selects gemini with an empty
  `LEGALAI_GEMINI_API_KEY=` placeholder, so the app fails fast until the key is pasted). Default
  model `gemini-3.5-flash-lite` (500 RPD free tier; ID not yet verified against `/models`), optional
  `LEGALAI_GEMINI_LIGHT_MODEL` for understanding / evidence check / question translation
  (`Orchestrator(light_llm=…)`, `LLMTranslator(light_llm=…)`). No LLM warm-up ping for Gemini
  (`warmup_llm=False`). start.ps1 skips the Ollama check for gemini. Privacy caveat in docs/security.md.
  `scripts/check_gemini.py`. 225 pytest; ruff + mypy clean. Not yet run against the live API.
- 2026-11-02 — Hands-free voice (ADR 0013): Silero VAD v5 in the browser (`@ricky0123/vad-web` 0.0.31,
  onnxruntime-web 1.31, single-threaded) ends the recording 1.5 s after speech (8 s no-speech →
  discard, 60 s cap, Stop still works). Lazy chunk; assets copied to `frontend/public/vad/`
  (git-ignored) by `scripts/copy-vad-assets.mjs` (npm predev/prebuild). Production CSP script-src
  + `'wasm-unsafe-eval'`. 26 vitest, 225 pytest, ruff + mypy + tsc clean. Live-verified in Chrome
  with a synthetic mic (TTS audio): auto-stop → ASR 9.9 s → answer 7.1 s via Gemini
  (gemini-3.5-flash-lite, so ADR 0012 now works against the live API) → spoken reply. The dev server
  (`python -m app`, reload on) picked up the Gemini switch by itself.
  Also live-verified hi (s.13(1)(ia)) and kn (clarification spoken → s.26 spoken). Open issue: one
  Bengali-script word in a Gemini kn translation — add a script check to translation validation.
- 2026-11-02 — Docs for GitHub: `docs/architecture.svg` (hand-written SVG diagram: browser → API →
  9-step orchestrator → LLM/index/speech/memory → offline pipeline; checked in Chrome), README
  rewritten (features, flow, stack, quick start incl. Gemini/Ollama, usage, eval numbers, layout,
  privacy, limitations, MMS CC-BY-NC), docs/architecture.md rewritten to the system as built (with a
  "changes from Phase 0" table). ADR 0013 notes it supersedes ADR 0009's "never auto-send".
  All phases 2–14 work committed and pushed (no Claude attribution), main fast-forwarded.
