"""Abuse protection (Phase 12): per-client rate limits, request size limits, security headers.

Every expensive endpoint (LLM answer, ASR, TTS) runs on one local GPU/CPU, so a single client
must not be able to monopolise it. Limits are in-memory (one process; see docs/security.md).
"""

import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from typing import cast

from fastapi import HTTPException, Request, status

from app.core.config import Settings
from app.providers.llm import LLMError

# Applied to every response. The CSP is production-only: /docs (dev) loads Swagger UI from a CDN.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "microphone=(self), camera=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
# 'wasm-unsafe-eval': the in-browser voice activity detector (ONNX runtime) compiles WebAssembly;
# it does not allow JavaScript eval.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
)


def log_safe_error(exc: Exception) -> dict[str, str]:
    """Log fields for an LLM-call failure without user text.

    Pydantic and JSON errors echo their input (the model's output, which paraphrases the
    user's question), so only their type is logged; ``LLMError`` messages describe transport.
    """
    if isinstance(exc, LLMError):
        return {"error_type": type(exc).__name__, "error": str(exc)[:200]}
    return {"error_type": type(exc).__name__}


JSON_BODY_LIMIT = 256 * 1024  # chat/tts/feedback bodies are a few KB


def body_limit(path: str, settings: Settings) -> int:
    """Largest accepted request body for ``path`` (checked from Content-Length)."""
    if path.endswith("/asr"):
        return int(settings.asr_max_upload_mb * 1024 * 1024) + 64 * 1024  # multipart overhead
    return JSON_BODY_LIMIT


class RateLimiter:
    """Sliding-window limiter: at most ``limit`` hits per ``window_s`` per key."""

    def __init__(self, window_s: float = 60.0, max_keys: int = 10_000) -> None:
        self._window = window_s
        self._max_keys = max_keys
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, now: float | None = None) -> float:
        """Record a hit; return 0 if allowed, else seconds until the next hit is allowed."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.pop(key, None) or deque()
            while hits and hits[0] <= now - self._window:
                hits.popleft()
            self._hits[key] = hits  # most recently used last
            if len(self._hits) > self._max_keys:
                self._hits.popitem(last=False)
            if len(hits) >= limit:
                return max(0.0, hits[0] + self._window - now)
            hits.append(now)
            return 0.0


def client_key(request: Request, trust_proxy: bool) -> str:
    """Client IP. ``X-Forwarded-For`` is honoured only behind a trusted reverse proxy."""
    if trust_proxy:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(bucket: str) -> Callable[[Request], None]:
    """FastAPI dependency limiting ``bucket`` ("chat" or "speech") per client."""

    def dependency(request: Request) -> None:
        settings = cast(Settings, request.app.state.settings)
        if not settings.rate_limit_enabled:
            return
        limit = (
            settings.rate_limit_chat_per_min
            if bucket == "chat"
            else (settings.rate_limit_speech_per_min)
        )
        limiter = cast(RateLimiter, request.app.state.rate_limiter)
        key = f"{bucket}:{client_key(request, settings.trust_proxy_headers)}"
        retry_after = limiter.check(key, limit)
        if retry_after > 0:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many requests. Please wait a moment and try again.",
                headers={"Retry-After": str(int(retry_after) + 1)},
            )

    return dependency
