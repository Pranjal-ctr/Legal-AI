# Kanoon AI — Multilingual Family Law Information Assistant

Research prototype of a multilingual (English, Hindi, Kannada) agentic RAG system that provides
source-grounded, explainable **information** about Indian family law.

> **Disclaimer:** This system provides general legal information, not legal advice, and is not a
> substitute for a qualified lawyer.

See [`docs/architecture.md`](docs/architecture.md) for the design and phase status.

## Repository layout

```text
backend/app/   FastAPI application (package `app`)
frontend/      React + TypeScript + Vite + Tailwind
scripts/       Offline CLIs (ingest, index, evaluate) — run from repo root
tests/         Python tests (unit/, integration/)
data/          raw/ processed/ evaluation/ (raw & processed are git-ignored)
models/        Local model weights cache (git-ignored)
docker/        Container definitions (later phases)
docs/          Architecture and ADRs
reports/       Evaluation outputs (git-ignored)
```

## Prerequisites

- Python 3.11+ (3.12 recommended) — [uv](https://docs.astral.sh/uv/) recommended
- Node.js 20+ and npm

## Setup

All Python commands run from the **repository root**.

```powershell
# Backend (with uv)
uv sync --extra dev
Copy-Item .env.example .env

# Backend (without uv)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env

# Frontend
cd frontend
npm install
Copy-Item .env.example .env
```

## Run

Two terminals:

```powershell
# Terminal 1 — backend on http://127.0.0.1:8000 (auto-reload in development)
uv run python -m app

# Terminal 2 — frontend on http://localhost:5173
cd frontend
npm run dev
```

- Health check: <http://127.0.0.1:8000/api/v1/health>
- API docs (development only): <http://127.0.0.1:8000/docs>
- UI: <http://localhost:5173> → should show **Connected**.

## Test & quality

```powershell
uv run pytest            # backend tests
uv run ruff check .      # lint
uv run ruff format .     # format
uv run mypy              # type-check

cd frontend
npm test                 # frontend tests
npm run typecheck
npm run build
```

## Configuration

Backend settings come from environment variables prefixed `LEGALAI_` (or `.env`); see
[`.env.example`](.env.example). Invalid values fail fast at startup. Never commit `.env`.
