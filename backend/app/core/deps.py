"""FastAPI dependencies shared across routers."""

import asyncio
from typing import Annotated, cast

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, status

from app.agents.orchestrator import Orchestrator
from app.core.config import Settings
from app.memory.crypto import Cipher, load_key
from app.memory.store import SessionStore
from app.providers.asr import ASRProvider
from app.providers.tts import TTSProvider
from app.rag.factory import build_asr, build_orchestrator, build_tts
from app.retrieval.corpus import CorpusNotFoundError
from app.retrieval.index import IndexNotReadyError

logger = structlog.get_logger(__name__)


def get_settings(request: Request) -> Settings:
    """Settings live on the app instance (no module globals), so tests can inject their own."""
    return cast(Settings, request.app.state.settings)


SettingsDep = Annotated[Settings, Depends(get_settings)]


async def ensure_orchestrator(app: FastAPI) -> Orchestrator:
    """Build the orchestrator once (loads corpus + checks index) and keep it on ``app.state``.

    Raises ``CorpusNotFoundError`` / ``IndexNotReadyError`` when setup is missing; the next
    call retries, so the server need not restart after `build_index`.
    """
    state = app.state
    service = cast(Orchestrator | None, getattr(state, "orchestrator", None))
    if service is not None:
        return service
    async with cast(asyncio.Lock, state.orchestrator_lock):
        service = getattr(state, "orchestrator", None)
        if service is None:
            service = await asyncio.to_thread(build_orchestrator, cast(Settings, state.settings))
            state.orchestrator = service
    return cast(Orchestrator, service)


async def get_orchestrator(request: Request) -> Orchestrator:
    """Missing setup (no ingest output / no index) answers 503 with the command to run."""
    try:
        return await ensure_orchestrator(request.app)
    except (CorpusNotFoundError, IndexNotReadyError) as exc:
        logger.warning("rag_not_ready", reason=str(exc))
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


OrchestratorDep = Annotated[Orchestrator, Depends(get_orchestrator)]


def build_session_store(settings: Settings) -> SessionStore:
    configured = settings.session_key.get_secret_value() if settings.session_key else None
    cipher = Cipher(load_key(configured, settings.sessions_dir))
    return SessionStore(
        settings.sessions_dir / "sessions.db", cipher, ttl_days=settings.session_ttl_days
    )


def get_session_store(request: Request, settings: SettingsDep) -> SessionStore:
    """Opened on first use (cheap; no await, so no race), closed on shutdown."""
    state = request.app.state
    store = cast(SessionStore | None, getattr(state, "session_store", None))
    if store is None:
        store = build_session_store(settings)
        state.session_store = store
    return store


SessionStoreDep = Annotated[SessionStore, Depends(get_session_store)]


def get_asr_instance(app: FastAPI) -> ASRProvider:
    state = app.state
    asr = cast(ASRProvider | None, getattr(state, "asr", None))
    if asr is None:
        asr = build_asr(cast(Settings, state.settings))
        state.asr = asr
    return asr


def get_asr(request: Request, settings: SettingsDep) -> ASRProvider:
    if not settings.asr_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Speech input is disabled.")
    return get_asr_instance(request.app)


ASRDep = Annotated[ASRProvider, Depends(get_asr)]


def get_tts_instance(app: FastAPI) -> TTSProvider:
    state = app.state
    tts = cast(TTSProvider | None, getattr(state, "tts", None))
    if tts is None:
        tts = build_tts(cast(Settings, state.settings))
        state.tts = tts
    return tts


def get_tts(request: Request, settings: SettingsDep) -> TTSProvider:
    if not settings.tts_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Speech output is disabled.")
    return get_tts_instance(request.app)


TTSDep = Annotated[TTSProvider, Depends(get_tts)]
