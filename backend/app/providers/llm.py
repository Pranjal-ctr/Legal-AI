"""LLM providers. Phase 3 ships one: a local model served by Ollama (``/api/chat``)."""

from typing import Any, Protocol

import httpx
import structlog

logger = structlog.get_logger(__name__)


class LLMError(RuntimeError):
    """The LLM backend is unreachable or returned an unusable response."""


class LLMProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    async def generate(
        self,
        system: str,
        prompt: str,
        *,
        temperature: float | None = None,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Return the model's reply to ``prompt`` under the ``system`` instruction.

        ``json_schema`` constrains the reply to JSON matching the schema (structured output).
        """
        ...


class OllamaLLM:
    """Non-streaming chat completion against a local Ollama server."""

    def __init__(
        self,
        base_url: str,
        model: str,
        temperature: float = 0.1,
        num_ctx: int = 8192,
        timeout_s: float = 180.0,
        keep_alive: str = "30m",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._temperature = temperature
        self._num_ctx = num_ctx
        self._timeout = httpx.Timeout(timeout_s, connect=5.0)
        self._keep_alive = keep_alive  # how long Ollama keeps the model in memory after a call
        self._transport = transport  # tests inject httpx.MockTransport

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
        options: dict[str, Any] = {
            "temperature": self._temperature if temperature is None else temperature,
            "num_ctx": self._num_ctx,
        }
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": False,  # grounded extraction, not open-ended reasoning: keep latency low
            "options": options,
            "keep_alive": self._keep_alive,
        }
        if json_schema is not None:
            payload["format"] = json_schema
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post("/api/chat", json=payload)
        except httpx.TimeoutException as exc:
            raise LLMError(f"Ollama did not answer within {self._timeout.read:.0f}s") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Cannot reach Ollama at {self._base_url}: {exc}") from exc

        if response.status_code != httpx.codes.OK:
            raise LLMError(f"Ollama returned HTTP {response.status_code}: {response.text[:300]}")
        try:
            data = response.json()
            content = data["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMError("Ollama returned an unexpected response body") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMError("Ollama returned an empty answer")

        logger.info(
            "llm_generated",
            model=self._model,
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
        )
        return content.strip()
