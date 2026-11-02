"""Serve the built React app (``frontend/dist``) from FastAPI (Phase 14).

One origin for UI and API: no CORS in deployment, the production CSP (``'self'``) fits, and
the microphone works on that origin (localhost or HTTPS). Unknown paths fall back to
``index.html`` (single-page app); ``/api/*`` keeps returning JSON 404s.
"""

from pathlib import Path

import structlog
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse

logger = structlog.get_logger(__name__)

# Vite fingerprints everything under assets/ (name.<hash>.js), so it can be cached forever.
IMMUTABLE = "public, max-age=31536000, immutable"


def mount_frontend(app: FastAPI, dist: Path, api_prefix: str) -> bool:
    """Add the catch-all UI route; call after the API routers. False if ``dist`` is not built."""
    root = dist.resolve()
    index = root / "index.html"
    if not index.is_file():
        return False
    api = api_prefix.strip("/") + "/"

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str) -> FileResponse:
        if path.startswith(api) or path == api.rstrip("/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            cache = IMMUTABLE if path.startswith("assets/") else "no-cache"
            return FileResponse(candidate, headers={"Cache-Control": cache})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    logger.info("frontend_mounted", dist=str(root))
    return True
