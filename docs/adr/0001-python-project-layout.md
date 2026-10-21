# ADR 0001 — Single Python project at the repository root

- **Status:** Accepted (Phase 1, 2026-10-07)

## Context

The Phase 0 design placed Python tests in `backend/tests/` and CLIs in a root `scripts/` folder.
CLIs must import backend code (`python -m scripts.ingest` uses `app.ingestion`), and tests, CLIs and
the server should share one environment and one lockfile.

## Decision

- One `pyproject.toml` at the repo root. The importable package `app` lives in `backend/app`
  (hatchling `packages = ["backend/app"]`), installed in editable mode.
- Python tests live in root `tests/` (`unit/`, `integration/`). Frontend tests are colocated in
  `frontend/src` (Vitest).
- All Python commands run from the repo root.

## Consequences

- `python -m app`, `python -m scripts.<cli>` and `pytest` work from the root without path hacks.
- Heavy optional stacks (speech, local LLMs) will be added as optional dependency groups
  (e.g. `.[speech]`) so the base install stays light.
