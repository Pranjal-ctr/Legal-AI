"""Application factory. Run with: `python -m app` or `uvicorn app.main:create_app --factory`."""

import asyncio
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1.router import api_router
from app.core.config import Settings, load_settings
from app.core.deps import ensure_orchestrator, get_asr_instance, get_tts_instance
from app.core.frontend import mount_frontend
from app.core.logging import configure_logging
from app.core.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from app.core.security import RateLimiter

logger = structlog.get_logger(__name__)


def initial_readiness(settings: Settings) -> dict[str, str]:
    """Per feature: loading | ready | unavailable | disabled | on_demand (no warm-up)."""
    warm = settings.warmup_on_startup and settings.environment != "test"
    state = "loading" if warm else "on_demand"
    return {
        "answers": state,
        "speech_input": state if settings.asr_enabled else "disabled",
        "speech_output": state if settings.tts_enabled else "disabled",
    }


async def _warm_up(app: FastAPI) -> None:
    """Load models in the background so the first question does not wait ~1 minute.

    Progress is published in ``app.state.readiness`` (GET /api/v1/ready) for the UI.
    """
    readiness: dict[str, str] = app.state.readiness
    settings = app.state.settings
    try:
        orchestrator = await ensure_orchestrator(app)
        await orchestrator.warmup()
        readiness["answers"] = "ready"
    except Exception as exc:  # e.g. corpus/index missing: requests report it with a 503
        logger.warning("warmup_skipped", reason=str(exc)[:200])
        readiness["answers"] = "unavailable"
    if settings.asr_enabled:
        try:
            asr = get_asr_instance(app)
            await asyncio.to_thread(asr.load)
            readiness["speech_input"] = "ready"
            logger.info("asr_ready", model=asr.model_name)
        except Exception as exc:  # e.g. speech extra not installed: /asr will answer 503
            readiness["speech_input"] = "unavailable"
            logger.warning("asr_warmup_skipped", reason=str(exc)[:200])
    if settings.tts_enabled:
        try:
            tts = get_tts_instance(app)
            for language in ("en", "hi", "kn"):
                await asyncio.to_thread(tts.load, language)
            readiness["speech_output"] = "ready"
            logger.info("tts_ready")
        except Exception as exc:  # e.g. speech extra not installed: /tts will answer 503
            readiness["speech_output"] = "unavailable"
            logger.warning("tts_warmup_skipped", reason=str(exc)[:200])


def create_app(app_settings: Settings | None = None) -> FastAPI:
    settings = app_settings if app_settings is not None else load_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    if settings.temp_dir is not None:  # e.g. keep spooled uploads off a full system drive
        settings.temp_dir.mkdir(parents=True, exist_ok=True)
        tempfile.tempdir = str(settings.temp_dir.resolve())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("app_started", environment=settings.environment, version=__version__)
        warmup: asyncio.Task[None] | None = None
        if settings.warmup_on_startup and settings.environment != "test":
            warmup = asyncio.create_task(_warm_up(app))
        yield
        if warmup is not None and not warmup.done():
            warmup.cancel()
        orchestrator = getattr(app.state, "orchestrator", None)
        if orchestrator is not None:
            orchestrator.close()
        session_store = getattr(app.state, "session_store", None)
        if session_store is not None:
            session_store.close()
        logger.info("app_stopped")

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        # Interactive docs are a development convenience; hide them in production.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.settings = settings
    app.state.orchestrator = None  # built lazily by app.core.deps.get_orchestrator
    app.state.orchestrator_lock = asyncio.Lock()
    app.state.readiness = initial_readiness(settings)
    app.state.rate_limiter = RateLimiter()
    app.state.asr = None  # built lazily by app.core.deps.get_asr
    app.state.tts = None  # built lazily by app.core.deps.get_tts
    app.state.session_store = None  # opened lazily by app.core.deps.get_session_store

    # Middleware added last runs first: CORS wraps everything, including error responses.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "Authorization", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    if settings.frontend_dist is not None:
        mount_frontend(app, settings.frontend_dist, settings.api_v1_prefix)
    return app
