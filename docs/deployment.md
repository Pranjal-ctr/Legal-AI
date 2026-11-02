# Deployment (Phase 14)

Kanoon AI runs as **one process serving UI and API on one origin** (`http://127.0.0.1:8000`),
plus a local **Ollama** server for the LLM. Model weights and data stay on local disk. No
question, answer or recording leaves the machine.

## Option A — Windows, one command (reference setup)

Prerequisites, once:

```powershell
uv sync --extra embed --extra speech      # Python 3.12 deps (+ CUDA torch on Windows)
cd frontend; npm ci; cd ..
ollama pull gemma4:e4b                    # LLM (6.6 GB download)
```

Then:

```powershell
.\scripts\start.ps1            # → http://127.0.0.1:8000
```

The script:

1. Keeps temp files on the repo drive.
2. Warns if Ollama is down (skipped when `LEGALAI_LLM_PROVIDER=gemini`, ADR 0012).
3. Ingests the corpus and builds the index on the first run.
4. Builds the UI if `frontend/dist` is missing (`-Rebuild` forces a rebuild).
5. Starts the server in **production mode**: no auto-reload, no `/docs`, strict CSP.

Production needs `LEGALAI_SESSION_KEY`. If neither the environment nor `.env` sets it, the
script uses `data/sessions/secret.key` (and creates it if needed) for that process only.
Models warm up in the background for about 1–2 minutes, and the header status pill shows
progress.

Development, with hot reload on both sides:

```powershell
uv run python -m app               # API :8000 (development: auto-reload, /docs)
cd frontend; npm run dev           # UI :5173, proxies /api to :8000
```

### Reference hardware and footprint

| Component | Where | Memory |
|---|---|---|
| gemma4:e4b (Ollama) + bge-m3 embedder + bge-reranker-v2-m3 (fp16) | GPU | ~7.6 GB VRAM together (measured) |
| faster-whisper large-v3-turbo (int8) | CPU | ~1.5 GB RAM |
| MMS-TTS hin/kan/eng | CPU | ~0.5 GB RAM |
| Disk: `models/` 6.2 GB, Ollama gemma4:e4b 6.6 GB, plus the Python environment (torch CUDA) | | |

Tested on an RTX 4060 Laptop (8 GB) with a 16-core CPU. On a GPU with less than 8 GB, set
`LEGALAI_EMBEDDING_DEVICE=cpu` and `LEGALAI_RERANKER_DEVICE=cpu`, or choose a smaller model
with `LEGALAI_OLLAMA_MODEL`. Expect slower answers.

## Option B — Docker Compose

`Dockerfile` (multi-stage: Node builds the UI, Python 3.12-slim with uv runs the API) and
`compose.yaml` (app + `ollama/ollama`, NVIDIA GPU reservation, app port bound to localhost
only).

```bash
cp .env.example .env               # set LEGALAI_SESSION_KEY (see the comment there)
docker compose up -d ollama
docker compose exec ollama ollama pull gemma4:e4b
docker compose run --rm app python -m scripts.ingest       # needs data/raw + data/family_law_dataset
docker compose run --rm app python -m scripts.build_index
docker compose up -d                                        # → http://127.0.0.1:8000
```

`./data` and `./models` are bind-mounted. The image runs as uid 10001, so make those
directories writable for it (e.g. `chown -R 10001 data models` on Linux). The corpus PDFs are
not distributed with the repository (see CLAUDE.md "Source corpus").

**Verification status:** `docker compose config` validates. The image was **not built** on the
reference machine: the Docker engine was not running, and its storage is on a full system
drive. The image includes torch with CUDA, so expect roughly 10 GB. Treat Option B as
untested until it has been built once.

## Exposing it beyond localhost

There is no authentication (see `docs/security.md`). To serve other devices:

1. Put an authenticating reverse proxy with TLS in front, e.g. Caddy with `basic_auth`.
   Browsers allow the microphone only on HTTPS or localhost.
2. Set `LEGALAI_TRUST_PROXY_HEADERS=true` so rate limits apply per real client, and keep the
   app itself bound to 127.0.0.1.
3. Never expose Ollama's port 11434.

## Operations

- Health: `GET /api/v1/health` (liveness). `GET /api/v1/ready` shows per-feature readiness
  (`answers`, `speech_input`, `speech_output`).
- Logs: structlog. Set `LEGALAI_LOG_JSON=true` for JSON lines. Logs never contain question or
  answer text.
- Sessions: `data/sessions/sessions.db` (encrypted). They expire after `LEGALAI_SESSION_TTL_DAYS`.
  Back up the key together with the database, or the sessions are unreadable.
- After a corpus change, re-run `scripts.ingest` and then `scripts.build_index`. The server
  refuses to start answering with a stale index (corpus fingerprint check).
