"""Request context middleware: request IDs, privacy-safe access logging, body size limits,
security headers and generic 500 handling."""

import re
import time
import uuid

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.config import Settings
from app.core.security import CONTENT_SECURITY_POLICY, SECURITY_HEADERS, body_limit

REQUEST_ID_HEADER = "X-Request-ID"

# Accept client-supplied IDs only if they are short and safe to log (prevents log injection).
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")
# Polled by the UI every few seconds: log at debug level only (keeps the access log readable).
_QUIET_PATHS = ("/health", "/ready")

logger = structlog.get_logger(__name__)


def _resolve_request_id(incoming: str | None) -> str:
    if incoming and _REQUEST_ID_PATTERN.fullmatch(incoming):
        return incoming
    return uuid.uuid4().hex


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = _resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        # Log the path only: query strings may carry user content.
        log = logger.bind(method=request.method, path=request.url.path)

        settings: Settings = request.app.state.settings
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > body_limit(request.url.path, settings):
            log.info("request_too_large", content_length=int(length))
            response: Response = JSONResponse(
                status_code=413, content={"detail": "The request is too large."}
            )
            return self._finish(response, request_id, settings)

        try:
            response = await call_next(request)
        except Exception:
            log.exception("request_failed", duration_ms=_elapsed_ms(start))
            response = JSONResponse(
                status_code=500,
                media_type="application/problem+json",
                content={
                    "type": "about:blank",
                    "title": "Internal Server Error",
                    "status": 500,
                    "request_id": request_id,
                },
            )
        else:
            quiet = response.status_code < 400 and request.url.path.endswith(_QUIET_PATHS)
            (log.debug if quiet else log.info)(
                "request_completed",
                status_code=response.status_code,
                duration_ms=_elapsed_ms(start),
            )
        return self._finish(response, request_id, settings)

    @staticmethod
    def _finish(response: Response, request_id: str, settings: Settings) -> Response:
        response.headers[REQUEST_ID_HEADER] = request_id
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if settings.is_production:
            response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        return response


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)
