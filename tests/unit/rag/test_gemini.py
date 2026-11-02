import asyncio
import json
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.providers.gemini import THINKING_HEADROOM_TOKENS, GeminiLLM
from app.providers.llm import LLMError
from app.rag.factory import build_llm


def _ok(text: str, **extra: Any) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2},
            **extra,
        },
    )


def _err(status: int, message: str = "", details: list[dict[str, Any]] | None = None) -> Any:
    return httpx.Response(
        status, json={"error": {"code": status, "message": message, "details": details or []}}
    )


class _Sleeps:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def _llm(handler: Any, model: str = "gemini-test", **kwargs: Any) -> GeminiLLM:
    return GeminiLLM(
        "secret-key",
        model,
        base_url="https://gemini.test/v1beta/",
        temperature=0.2,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def test_generate_sends_system_instruction_schema_and_key_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok('```json\n{"a": 1}\n```')

    schema = {"type": "object", "properties": {"a": {"type": "integer"}}}
    reply = asyncio.run(_llm(handler).generate("sys", "user", json_schema=schema, max_tokens=50))

    assert reply == '{"a": 1}'  # code fence stripped for JSON replies
    request = seen[0]
    assert str(request.url) == "https://gemini.test/v1beta/models/gemini-test:generateContent"
    assert request.headers["x-goog-api-key"] == "secret-key"
    assert "secret-key" not in str(request.url)
    body = json.loads(request.content)
    assert body["systemInstruction"] == {"parts": [{"text": "sys"}]}
    assert body["contents"] == [{"role": "user", "parts": [{"text": "user"}]}]
    config = body["generationConfig"]
    assert config["temperature"] == 0.2
    assert config["maxOutputTokens"] == 50 + THINKING_HEADROOM_TOKENS
    assert config["responseMimeType"] == "application/json"
    assert config["responseJsonSchema"] == schema
    assert config["thinkingConfig"] == {"thinkingLevel": "minimal"}


def test_thought_parts_are_skipped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        parts = [{"text": "thinking...", "thought": True}, {"text": "Answer [1]."}]
        return httpx.Response(200, json={"candidates": [{"content": {"parts": parts}}]})

    assert asyncio.run(_llm(handler).generate("s", "p")) == "Answer [1]."


def test_models_prefix_is_accepted() -> None:
    assert _llm(lambda _: _ok("x"), model="models/gemini-x").model_name == "gemini-x"


def test_gemma_gets_compat_request() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return _ok('{"a": 1}')

    llm = _llm(handler, model="gemma-4-31b-it")
    asyncio.run(llm.generate("sys", "user", json_schema={"type": "object"}))

    body = seen[0]
    assert "systemInstruction" not in body
    text = body["contents"][0]["parts"][0]["text"]
    assert text.startswith("sys\n\nuser")
    assert '{"type": "object"}' in text
    assert "responseJsonSchema" not in body["generationConfig"]
    assert "thinkingConfig" not in body["generationConfig"]


def test_bad_request_switches_to_compat_once() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if "systemInstruction" in body:
            return _err(400, "Developer instruction is not enabled")
        return _ok("fine")

    llm = _llm(handler)
    assert asyncio.run(llm.generate("sys", "user")) == "fine"
    assert asyncio.run(llm.generate("sys", "user")) == "fine"
    assert len(seen) == 3  # one rejected request, then compat mode is remembered


def test_invalid_key_is_not_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _err(400, "API key not valid.", [{"reason": "API_KEY_INVALID"}])

    with pytest.raises(LLMError, match="rejected the API key"):
        asyncio.run(_llm(handler).generate("s", "p"))
    assert len(calls) == 1


def test_per_minute_rate_limit_waits_retry_delay() -> None:
    responses = [
        _err(429, "quota", [{"retryDelay": "7s"}]),
        _ok("after wait"),
    ]
    sleeps = _Sleeps()

    reply = asyncio.run(_llm(lambda _: responses.pop(0), sleep=sleeps).generate("s", "p"))

    assert reply == "after wait"
    assert sleeps.waits == [7.0]


def test_long_retry_delay_fails_fast() -> None:
    sleeps = _Sleeps()
    llm = _llm(lambda _: _err(429, "q", [{"retryDelay": "45s"}]), sleep=sleeps)

    with pytest.raises(LLMError, match="rate limit reached"):
        asyncio.run(llm.generate("s", "p"))
    assert sleeps.waits == []


def test_daily_quota_fails_fast_with_reset_hint() -> None:
    details = [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]
    sleeps = _Sleeps()
    llm = _llm(lambda _: _err(429, "q", details), sleep=sleeps)

    with pytest.raises(LLMError, match="daily request quota"):
        asyncio.run(llm.generate("s", "p"))
    assert sleeps.waits == []


def test_server_errors_are_retried_then_raise() -> None:
    sleeps = _Sleeps()
    llm = _llm(lambda _: _err(503, "overloaded"), sleep=sleeps)

    with pytest.raises(LLMError, match="HTTP 503"):
        asyncio.run(llm.generate("s", "p"))
    assert len(sleeps.waits) == 2


@pytest.mark.parametrize(
    ("response", "match"),
    [
        (httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}), "blocked"),
        (httpx.Response(200, json={"candidates": []}), "no answer"),
        (
            httpx.Response(200, json={"candidates": [{"finishReason": "MAX_TOKENS"}]}),
            "MAX_TOKENS",
        ),
        (httpx.Response(200, text="not json"), "unexpected"),
        (_err(404, "model not found"), "not found"),
    ],
)
def test_unusable_responses_raise_llm_error(response: httpx.Response, match: str) -> None:
    with pytest.raises(LLMError, match=match):
        asyncio.run(_llm(lambda _: response).generate("s", "p"))


def test_connection_failure_hides_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LLMError, match="Cannot reach the Gemini API"):
        asyncio.run(_llm(handler).generate("s", "p"))


def test_empty_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        GeminiLLM("  ", "gemini-test")


def test_settings_require_key_for_gemini() -> None:
    with pytest.raises(ValidationError, match="LEGALAI_GEMINI_API_KEY"):
        Settings(_env_file=None, llm_provider="gemini")  # type: ignore[call-arg]
    with pytest.raises(ValidationError, match="LEGALAI_GEMINI_API_KEY"):
        Settings(_env_file=None, llm_provider="gemini", gemini_api_key="")  # type: ignore[call-arg]


def test_factory_builds_gemini_main_and_light_models() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        llm_provider="gemini",
        gemini_api_key="k",
        gemini_model="main-model",
        gemini_light_model="light-model",
    )
    main, light = build_llm(settings), build_llm(settings, light=True)

    assert isinstance(main, GeminiLLM)
    assert (main.model_name, light.model_name) == ("main-model", "light-model")
    unset = Settings(_env_file=None, llm_provider="gemini", gemini_api_key="k")  # type: ignore[call-arg]
    assert build_llm(unset, light=True).model_name == unset.gemini_model
