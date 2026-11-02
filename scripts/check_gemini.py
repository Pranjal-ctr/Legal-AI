"""Check the Gemini API setup (ADR 0012): key, model IDs, plain + JSON replies.

    uv run python -m scripts.check_gemini          # list models, test the configured ones
    uv run python -m scripts.check_gemini --list   # only list the model IDs this key can use

Reads LEGALAI_* settings from the environment / .env. Never prints the API key. Each test
makes 2 requests per configured model (counts against the free-tier daily quota).
"""

import argparse
import asyncio
import json
import sys

import httpx
from pydantic import BaseModel

from app.core.config import Settings, load_settings
from app.providers.gemini import GeminiLLM
from app.providers.llm import LLMError


class _Probe(BaseModel):
    topic: str
    in_scope: bool


def _key(settings: Settings) -> str:
    if settings.gemini_api_key is None:
        sys.exit("LEGALAI_GEMINI_API_KEY is not set (paste it into .env)")
    return settings.gemini_api_key.get_secret_value().strip()


def list_models(settings: Settings) -> list[str]:
    response = httpx.get(
        f"{settings.gemini_base_url.rstrip('/')}/models",
        params={"pageSize": 1000},
        headers={"x-goog-api-key": _key(settings)},
        timeout=30,
    )
    if response.status_code != httpx.codes.OK:
        message = response.json().get("error", {}).get("message", "") if response.content else ""
        sys.exit(f"Listing models failed: HTTP {response.status_code} {message[:200]}")
    return sorted(
        m["name"].removeprefix("models/")
        for m in response.json().get("models", [])
        if "generateContent" in m.get("supportedGenerationMethods", [])
    )


async def probe(settings: Settings, model: str) -> bool:
    llm = GeminiLLM(
        _key(settings),
        model,
        base_url=settings.gemini_base_url,
        thinking_level=settings.gemini_thinking_level,
        max_retry_wait_s=settings.gemini_max_retry_wait_s,
    )
    try:
        plain = await llm.generate("Reply with exactly: OK", "Say OK.", max_tokens=5)
        raw = await llm.generate(
            "Classify the question. Reply in JSON.",
            "Question: How do I file for divorce under the Hindu Marriage Act?",
            json_schema=_Probe.model_json_schema(),
            max_tokens=60,
        )
        parsed = _Probe.model_validate(json.loads(raw))
    except (LLMError, ValueError) as exc:
        print(f"  {model}: FAILED: {type(exc).__name__}: {str(exc)[:200]}")
        return False
    print(f"  {model}: OK (plain {plain!r}; JSON {parsed.model_dump()})")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="only list usable model IDs")
    args = parser.parse_args()
    settings = load_settings()

    models = list_models(settings)
    print(f"{len(models)} models support generateContent with this key:")
    for name in models:
        print(f"  {name}")
    if args.list:
        return

    configured = [settings.gemini_model]
    if settings.gemini_light_model and settings.gemini_light_model not in configured:
        configured.append(settings.gemini_light_model)
    print("\nTesting configured models:")
    ok = True
    for model in configured:
        if model not in models:
            print(f"  {model}: not in the list above; set LEGALAI_GEMINI_MODEL to a listed ID")
            ok = False
            continue
        ok = asyncio.run(probe(settings, model)) and ok
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
