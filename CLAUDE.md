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
| 2 | Ingestion: HMA 1955 + 48 judgments → hierarchical chunks + 20 gold queries (ADR 0002) | Built & tested 2026-10-30 — not yet committed |
| 3 | Baseline RAG + minimal chat UI | **Next — awaiting `START PHASE 3`** |
| 4–15 | Hybrid retrieval, multilingual, query understanding, agentic RAG, memory, ASR, TTS, UI, security, evaluation, deployment, research write-up | — |

## Layout (ADR 0001: single Python project at repo root)

```text
backend/app/          importable package `app` (hatchling packages = ["backend/app"])
  main.py             create_app() factory; CORS + RequestContextMiddleware (X-Request-ID)
  __main__.py         `python -m app` → uvicorn
  core/config.py      Settings (pydantic-settings, prefix LEGALAI_, .env), load_settings()
  core/logging.py     structlog config (console or JSON)
  core/middleware.py  request id + access logging
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
scripts/ingest.py     `python -m scripts.ingest` → data/processed/{documents,chunks}.jsonl,
                      ingest_report.json, data/manifest.json (committed)
frontend/src/         App.tsx, components/BackendStatus.tsx, hooks/useHealth.ts,
                      services/api.ts, types/api.ts; tests colocated (Vitest)
scripts/              offline CLIs, run as `python -m scripts.<cli>` from repo root
tests/                unit/, integration/ (pytest; pythonpath = backend, .)
data/                 raw/ processed/ family_law_dataset/ (git-ignored), manifest.json,
                      evaluation/gold_queries.jsonl (20 draft queries, chunk ids + verbatim evidence)
models/ reports/      git-ignored caches/outputs
```

## Commands (run from repo root)

```powershell
uv sync --extra dev --extra ingest
uv run python -m scripts.ingest   # ~4 min first run (PDF extraction), seconds when cached
uv run python -m app          # backend :8000 (health: /api/v1/health, docs: /docs in dev)
uv run pytest; uv run ruff check .; uv run ruff format .; uv run mypy
cd frontend; npm install; npm run dev   # :5173
npm test; npm run typecheck; npm run build
```

CI (`.github/workflows/ci.yml`): backend installs `.[dev,ingest]`; ruff check + format --check + mypy (strict) + pytest on
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
- Stores: PostgreSQL (source of truth), Qdrant (vectors by `chunk_id`), Redis (state/cache).
- Heavy stacks go in optional dependency groups (e.g. `.[speech]`).

## Source corpus (data/raw — git-ignored, so provenance is recorded here)

| File | Source | Notes |
|---|---|---|
| `data/family_law_dataset/` | 49 judgment PDFs supplied by the user: Supreme Court from Digital S.C.R. (digiscr.sci.gov.in), High Courts from eCourts (judgments.ecourts.gov.in). Per-file sha256 + extracted metadata in `data/manifest.json`. | 48 unique (Dhananjay Rathi, 2026 INSC 360, duplicated across divorce + domestic_violence → one doc, both topics). Kept by user choice though off-topic: Balaji Formalin v. UoI (poisons rules), Sardari Lal v. Bishan Dass (will). `acts and laws/` folder is empty. |
| `data/raw/hma1955.pdf` | Punjab & Haryana High Court mirror of the Legislative Dept. text: https://www.highcourtchd.gov.in/hclscc/subpages/pdf_files/4.pdf (downloaded 2026-10-23) | 13 pages, text-extractable (pypdf). Amendments through Act 6 of 2019 (leprosy ground removed). sha256 `11547fa0…2e3a295a`. India Code (indiacode.nic.in, handle 123456789/1560) is canonical but blocks scripted downloads (403/504). |

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
