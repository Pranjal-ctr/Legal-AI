from app.core.config import Settings
from app.core.security import RateLimiter, body_limit


def test_rate_limiter_allows_limit_then_blocks_until_window_passes() -> None:
    limiter = RateLimiter(window_s=60)

    assert [limiter.check("a", 2, now=t) for t in (0.0, 1.0)] == [0.0, 0.0]
    assert limiter.check("a", 2, now=2.0) == 58.0  # oldest hit expires at t=60
    assert limiter.check("b", 2, now=2.0) == 0.0  # other clients are unaffected
    assert limiter.check("a", 2, now=60.5) == 0.0


def test_rate_limiter_forgets_least_recent_keys() -> None:
    limiter = RateLimiter(max_keys=2)
    for key in ("a", "b", "c"):
        limiter.check(key, 1, now=0.0)

    assert limiter.check("a", 1, now=1.0) == 0.0  # "a" was evicted, so it starts afresh


def test_body_limits() -> None:
    settings = Settings(_env_file=None, environment="test", asr_max_upload_mb=1)  # type: ignore[call-arg]

    assert body_limit("/api/v1/chat", settings) == 256 * 1024
    assert body_limit("/api/v1/asr", settings) > 1024 * 1024


def test_log_safe_error_drops_echoed_input() -> None:
    from pydantic import BaseModel, ValidationError

    from app.core.security import log_safe_error
    from app.providers.llm import LLMError

    class Model(BaseModel):
        n: int

    try:
        Model.model_validate({"n": "my husband beats me"})
    except ValidationError as exc:
        fields = log_safe_error(exc)
    assert fields == {"error_type": "ValidationError"}
    assert log_safe_error(LLMError("Ollama timed out"))["error"] == "Ollama timed out"
