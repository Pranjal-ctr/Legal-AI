"""Google Gemini API provider (ADR 0012): the same ``LLMProvider`` protocol as ``OllamaLLM``.

One API key covers every model; the model is named per request in the URL
(``/models/{model}:generateContent``), so switching models is a setting, not new code.

Gemma models served by the API reject system instructions and JSON mode, so they get
"compat" requests: the instruction is folded into the user turn and the JSON schema is stated
in the prompt. A Gemini model that rejects an optional feature (HTTP 400) is switched to compat
mode once and stays there.

Free-tier limits are per model: a per-minute 429 is retried after the server's ``retryDelay``
(if short); a used-up daily quota fails at once with a clear message. The API key travels in
the ``x-goog-api-key`` header, never in the URL, and is never logged.
"""

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import structlog

from app.providers.llm import LLMError

logger = structlog.get_logger(__name__)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
# maxOutputTokens also counts "thinking" tokens on thinking models; without headroom a short
# budget (e.g. the 200-token evidence check) can be spent before any answer text is written.
THINKING_HEADROOM_TOKENS = 512
_MAX_RETRIES = 2
_SERVER_ERROR_WAIT_S = 2.0
_DEFAULT_RATE_WAIT_S = 5.0

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
_DELAY = re.compile(r"^(\d+(?:\.\d+)?)s$")

Sleep = Callable[[float], Awaitable[None]]


class GeminiLLM:
    """Non-streaming ``generateContent`` against the Gemini API."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        temperature: float = 0.1,
        timeout_s: float = 60.0,
        thinking_level: str | None = "minimal",
        max_retry_wait_s: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Gemini API key is empty")
        self._api_key = api_key.strip()
        self._model = model.removeprefix("models/")
        self._base_url = base_url.rstrip("/")
        self._temperature = temperature
        self._timeout = httpx.Timeout(timeout_s, connect=10.0)
        self._thinking_level = thinking_level
        self._max_retry_wait_s = max_retry_wait_s
        self._transport = transport  # tests inject httpx.MockTransport
        self._sleep = sleep
        self._compat = self._model.lower().startswith("gemma")

    @property
    def model_name(self) -> str:
        return self._model

    async def generate(
        self,
        system: str,
        prompt: str,
        *,
        temperature: float | None = None,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> str:
        temp = self._temperature if temperature is None else temperature
        payload = self._payload(system, prompt, temp, json_schema, max_tokens)
        retries = 0
        while True:
            response = await self._post(payload)
            if response.status_code == httpx.codes.OK:
                break
            if (
                response.status_code == httpx.codes.BAD_REQUEST
                and not self._compat
                and not _is_key_error(response)
            ):
                logger.warning(
                    "gemini_compat_mode", model=self._model, error=_error_message(response)[:200]
                )
                self._compat = True
                payload = self._payload(system, prompt, temp, json_schema, max_tokens)
                continue
            wait = self._retry_wait(response) if retries < _MAX_RETRIES else None
            if wait is None:
                raise LLMError(self._describe(response))
            retries += 1
            logger.info("gemini_retry", model=self._model, status=response.status_code, wait_s=wait)
            await self._sleep(wait)

        text, data = self._text(response)
        if json_schema is not None:
            match = _FENCE.match(text)
            if match:
                text = match.group(1).strip()
        usage = data.get("usageMetadata") or {}
        logger.info(
            "llm_generated",
            model=self._model,
            prompt_tokens=usage.get("promptTokenCount"),
            completion_tokens=usage.get("candidatesTokenCount"),
            thinking_tokens=usage.get("thoughtsTokenCount"),
        )
        return text

    # ---- request ------------------------------------------------------------------------

    def _payload(
        self,
        system: str,
        prompt: str,
        temperature: float,
        json_schema: dict[str, Any] | None,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        config: dict[str, Any] = {"temperature": temperature}
        if max_tokens is not None:
            config["maxOutputTokens"] = max_tokens + THINKING_HEADROOM_TOKENS
        if self._compat:
            text = f"{system}\n\n{prompt}"
            if json_schema is not None:
                text += (
                    "\n\nReply with only a JSON object (no code fences) matching this JSON "
                    f"schema:\n{json.dumps(json_schema, ensure_ascii=False)}"
                )
            return {
                "contents": [{"role": "user", "parts": [{"text": text}]}],
                "generationConfig": config,
            }
        if json_schema is not None:
            config["responseMimeType"] = "application/json"
            config["responseJsonSchema"] = json_schema
        if self._thinking_level:
            config["thinkingConfig"] = {"thinkingLevel": self._thinking_level}
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": config,
        }

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=self._timeout, transport=self._transport
            ) as client:
                return await client.post(
                    f"/models/{self._model}:generateContent",
                    json=payload,
                    headers={"x-goog-api-key": self._api_key},
                )
        except httpx.TimeoutException as exc:
            raise LLMError(f"Gemini did not answer within {self._timeout.read:.0f}s") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Cannot reach the Gemini API: {type(exc).__name__}") from exc

    # ---- response -----------------------------------------------------------------------

    def _text(self, response: httpx.Response) -> tuple[str, dict[str, Any]]:
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError("Gemini returned an unexpected response body") from exc
        if not isinstance(data, dict):
            raise LLMError("Gemini returned an unexpected response body")
        candidates = data.get("candidates") or []
        if not candidates:
            block = (data.get("promptFeedback") or {}).get("blockReason")
            raise LLMError(
                f"Gemini blocked the request ({block})" if block else "Gemini returned no answer"
            )
        candidate = candidates[0] if isinstance(candidates[0], dict) else {}
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(
            p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought")
        ).strip()
        if not text:
            reason = candidate.get("finishReason", "unknown")
            raise LLMError(f"Gemini returned an empty answer (finishReason={reason})")
        return text, data

    def _retry_wait(self, response: httpx.Response) -> float | None:
        """Seconds to wait before retrying, or None when retrying cannot help."""
        if response.status_code in (500, 502, 503, 504):
            return _SERVER_ERROR_WAIT_S
        if response.status_code != httpx.codes.TOO_MANY_REQUESTS or _is_daily_quota(response):
            return None
        wait = _retry_delay(response) or _DEFAULT_RATE_WAIT_S
        return wait if wait <= self._max_retry_wait_s else None

    def _describe(self, response: httpx.Response) -> str:
        status = response.status_code
        if status == httpx.codes.TOO_MANY_REQUESTS:
            if _is_daily_quota(response):
                return (
                    f"Gemini daily request quota for {self._model} is used up "
                    "(the free tier resets at midnight Pacific time)"
                )
            return f"Gemini rate limit reached for {self._model}; try again in a minute"
        if _is_key_error(response) or status == httpx.codes.FORBIDDEN:
            return "Gemini rejected the API key (check LEGALAI_GEMINI_API_KEY)"
        if status == httpx.codes.NOT_FOUND:
            return f"Gemini model {self._model!r} not found (check LEGALAI_GEMINI_MODEL)"
        return f"Gemini returned HTTP {status}: {_error_message(response)[:300]}"


def _error(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    error = body.get("error") if isinstance(body, dict) else None
    return error if isinstance(error, dict) else {}


def _error_message(response: httpx.Response) -> str:
    return str(_error(response).get("message") or response.text)


def _details(response: httpx.Response) -> list[dict[str, Any]]:
    details = _error(response).get("details") or []
    return [d for d in details if isinstance(d, dict)]


def _is_key_error(response: httpx.Response) -> bool:
    if any(d.get("reason") == "API_KEY_INVALID" for d in _details(response)):
        return True
    return "api key" in _error_message(response).lower()


def _is_daily_quota(response: httpx.Response) -> bool:
    for detail in _details(response):
        for violation in detail.get("violations") or []:
            if isinstance(violation, dict) and "PerDay" in str(violation.get("quotaId", "")):
                return True
    return False


def _retry_delay(response: httpx.Response) -> float | None:
    for detail in _details(response):
        match = _DELAY.match(str(detail.get("retryDelay", "")))
        if match:
            return float(match.group(1))
    header = response.headers.get("retry-after", "")
    return float(header) if header.isdigit() else None
