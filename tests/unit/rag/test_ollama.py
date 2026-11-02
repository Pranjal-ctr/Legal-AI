import asyncio
import json

import httpx
import pytest

from app.providers.llm import LLMError, OllamaLLM


def _llm(transport: httpx.MockTransport) -> OllamaLLM:
    return OllamaLLM(
        "http://ollama.test/", "m1", temperature=0.2, num_ctx=4096, transport=transport
    )


def test_generate_posts_chat_request_and_returns_content() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"message": {"content": "  Answer [1].  "}, "eval_count": 3}
        )

    reply = asyncio.run(_llm(httpx.MockTransport(handler)).generate("sys", "user"))

    assert reply == "Answer [1]."
    assert str(seen[0].url) == "http://ollama.test/api/chat"
    body = json.loads(seen[0].content)
    assert body["model"] == "m1"
    assert body["stream"] is False
    assert body["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user"},
    ]
    assert body["options"] == {"temperature": 0.2, "num_ctx": 4096}
    assert body["keep_alive"] == "30m"  # model stays loaded between questions


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="model not found"),
        httpx.Response(200, json={"unexpected": True}),
        httpx.Response(200, json={"message": {"content": "   "}}),
        httpx.Response(200, text="not json"),
    ],
)
def test_bad_responses_raise_llm_error(response: httpx.Response) -> None:
    llm = _llm(httpx.MockTransport(lambda _: response))

    with pytest.raises(LLMError):
        asyncio.run(llm.generate("sys", "user"))


def test_connection_failure_raises_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LLMError, match="Cannot reach Ollama"):
        asyncio.run(_llm(httpx.MockTransport(handler)).generate("sys", "user"))


def test_timeout_raises_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(LLMError, match="did not answer"):
        asyncio.run(_llm(httpx.MockTransport(handler)).generate("sys", "user"))
