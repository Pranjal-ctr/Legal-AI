import pytest
from pydantic import ValidationError

from app.core.config import Settings


def make_settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("LEGALAI_ENVIRONMENT", "LEGALAI_PORT", "LEGALAI_CORS_ORIGINS"):
        monkeypatch.delenv(var, raising=False)

    settings = make_settings()

    assert settings.environment == "development"
    assert settings.port == 8000
    assert settings.api_v1_prefix == "/api/v1"
    assert "http://localhost:5173" in settings.cors_origins


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEGALAI_ENVIRONMENT", "production")
    monkeypatch.setenv("LEGALAI_PORT", "9001")
    monkeypatch.setenv("LEGALAI_LOG_JSON", "true")
    monkeypatch.setenv("LEGALAI_CORS_ORIGINS", '["https://example.org"]')

    settings = make_settings()

    assert settings.environment == "production"
    assert settings.is_production
    assert settings.port == 9001
    assert settings.log_json is True
    assert settings.cors_origins == ["https://example.org"]


@pytest.mark.parametrize(
    ("var", "value"),
    [("LEGALAI_ENVIRONMENT", "staging"), ("LEGALAI_PORT", "70000"), ("LEGALAI_LOG_LEVEL", "LOUD")],
)
def test_invalid_values_are_rejected(monkeypatch: pytest.MonkeyPatch, var: str, value: str) -> None:
    monkeypatch.setenv(var, value)

    with pytest.raises(ValidationError):
        make_settings()
