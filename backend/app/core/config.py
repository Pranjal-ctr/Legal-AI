"""Application settings, loaded from environment variables (prefix ``LEGALAI_``) and ``.env``."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LEGALAI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Kanoon AI"
    environment: Environment = "development"
    log_level: LogLevel = "INFO"
    log_json: bool = False

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    api_v1_prefix: str = "/api/v1"

    # Parsed from a JSON list, e.g. LEGALAI_CORS_ORIGINS=["http://localhost:5173"]
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


def load_settings() -> Settings:
    """Build settings from the current environment. Called once per app instance."""
    return Settings()
