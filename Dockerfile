# Kanoon AI: UI + API in one image (Phase 14). Ollama runs as a separate service (compose.yaml).
# Data (corpus, index, sessions) and model weights are mounted, not baked in: see docs/deployment.md.

# ---- UI build ----------------------------------------------------------------------------------
FROM node:22-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- API ---------------------------------------------------------------------------------------
FROM python:3.12-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.9.16 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_CACHE_DIR=/tmp/uv-cache PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1
WORKDIR /srv
# ffmpeg libraries come with the PyAV wheel; libgomp is needed by CTranslate2 (faster-whisper).
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra embed --extra speech --no-install-project
COPY backend/ backend/
COPY scripts/ scripts/
RUN uv sync --frozen --no-dev --extra embed --extra speech
COPY --from=ui /ui/dist frontend/dist

RUN useradd --create-home --uid 10001 kanoon && mkdir -p data models .tmp && chown -R kanoon data models .tmp
USER kanoon
ENV LEGALAI_ENVIRONMENT=production LEGALAI_HOST=0.0.0.0 LEGALAI_PORT=8000 LEGALAI_TEMP_DIR=.tmp \
    LEGALAI_LOG_JSON=true
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health')"
CMD ["python", "-m", "app"]
