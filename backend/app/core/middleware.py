"""Request context middleware: request IDs, privacy-safe access logging, generic 500 handling."""

import re
import time
import uuid

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

REQUEST_ID_HEADER = "X-Request-ID"

# Accept client-supplied IDs only if they are short and safe to log (prevents log injection).
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")

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
            log.info(
                "request_completed",
                status_code=response.status_code,
                duration_ms=_elapsed_ms(start),
            )

        response.headers[REQUEST_ID_HEADER] = request_id
        return response


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)
