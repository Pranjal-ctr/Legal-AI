from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Request

from app import __version__
from app.core.deps import SettingsDep
from app.schemas.health import HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDep) -> HealthResponse:
    """Liveness check. Readiness (DB, vector store, providers) arrives with those components."""
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        version=__version__,
        environment=settings.environment,
        timestamp=datetime.now(UTC),
    )


@router.get("/ready", response_model=ReadyResponse)
async def ready(request: Request) -> ReadyResponse:
    """Readiness of each feature (models load in the background after startup)."""
    readiness = dict(cast(dict[str, str], request.app.state.readiness))
    if getattr(request.app.state, "orchestrator", None) is not None and readiness["answers"] in (
        "on_demand",
        "unavailable",
    ):
        readiness["answers"] = "ready"  # built by a request (or a retry after `build_index`)
    return ReadyResponse.model_validate(readiness)
