"""Application settings, loaded from environment variables (prefix ``LEGALAI_``) and ``.env``."""

from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
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

    # Corpus root: raw/ (statutes), family_law_dataset/ (judgments), processed/ (ingest output).
    data_dir: Path = Path("data")

    # Retrieval (Phase 3). Model weights are cached under models_dir (git-ignored).
    index_dir: Path = Path("data/index")
    # Unset: embedded Qdrant under index_dir/qdrant. Set (e.g. http://localhost:6333): server.
    qdrant_url: str | None = None
    models_dir: Path = Path("models")
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: Literal["auto", "cpu", "cuda"] = "auto"
    retrieval_top_k: int = Field(default=6, ge=1, le=20)
    # Phase 4/5: hybrid = dense + BM25 fused with RRF, then cross-encoder reranking fused with
    # the first stage. Rerank is on: +0.05-0.10 hit@6 on hi/kn queries (ADR 0005).
    retrieval_mode: Literal["dense", "bm25", "hybrid"] = "hybrid"
    retrieval_candidates: int = Field(default=30, ge=5, le=200)  # fused pool sent to reranker
    rerank_enabled: bool = True
    rerank_strategy: Literal["replace", "fuse"] = "fuse"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_device: Literal["auto", "cpu", "cuda"] = "auto"

    # Agentic orchestration (Phase 7): evidence assessment + at most one follow-up retrieval.
    agent_max_rounds: int = Field(default=2, ge=1, le=2)
    agent_assess_evidence: bool = True
    agent_max_sources: int = Field(default=8, ge=1, le=20)

    # Generation (Phase 3): local LLM via Ollama, or the Gemini API (ADR 0012).
    llm_provider: Literal["ollama", "gemini"] = "ollama"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "gemma4:e4b"
    llm_temperature: float = Field(default=0.1, ge=0.0, le=1.0)
    llm_num_ctx: int = Field(default=8192, ge=2048)
    llm_timeout_s: float = Field(default=180.0, gt=0)
    llm_keep_alive: str = "30m"  # Ollama keeps the model loaded this long after each call

    # Gemini API (ADR 0012): one key covers every model; the model is named per request.
    # Questions leave this machine: Google may use free-tier prompts to improve its products.
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash-lite"  # answers + answer translation
    # Short calls (query understanding, evidence check, question translation). Unset = gemini_model.
    gemini_light_model: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_thinking_level: Literal["minimal", "low", "medium", "high"] | None = "minimal"
    gemini_timeout_s: float = Field(default=60.0, gt=0)
    gemini_max_retry_wait_s: float = Field(default=20.0, ge=0, le=120)  # per-minute 429 retry

    # Speech recognition (Phase 9): faster-whisper on CPU (the GPU is full with the LLM).
    asr_enabled: bool = True
    asr_model: str = "large-v3-turbo"  # or "medium" / "small" (faster, less accurate in hi/kn)
    asr_device: Literal["cpu", "cuda"] = "cpu"
    asr_compute_type: str = "int8"
    asr_cpu_threads: int = Field(default=0, ge=0)  # 0 = all cores
    asr_beam_size: int = Field(default=1, ge=1, le=10)
    asr_max_seconds: float = Field(default=60.0, gt=0, le=300)
    asr_max_upload_mb: float = Field(default=10.0, gt=0, le=100)

    # Speech output (Phase 10): MMS-TTS (VITS) on CPU; models load per language.
    tts_enabled: bool = True
    tts_cpu_threads: int = Field(default=0, ge=0)  # 0 = torch default
    tts_max_chars: int = Field(default=1200, ge=50, le=5000)  # per request

    # Abuse protection (Phase 12): per-client requests per minute on the expensive endpoints.
    rate_limit_enabled: bool = True
    rate_limit_chat_per_min: int = Field(default=12, ge=1)
    rate_limit_speech_per_min: int = Field(default=40, ge=1)  # TTS is called per sentence
    # Honour X-Forwarded-For (only behind a trusted reverse proxy, else clients can spoof it).
    trust_proxy_headers: bool = False

    # Built UI served by FastAPI at / (Phase 14); ignored if not built (`npm run build`).
    frontend_dist: Path | None = Path("frontend/dist")

    # Temporary files (spooled uploads, downloads). Unset = system temp dir.
    temp_dir: Path | None = None

    # Load all models in the background at startup (skipped when environment == "test").
    warmup_on_startup: bool = True

    # Conversation memory (Phase 8): encrypted SQLite sessions under sessions_dir.
    sessions_dir: Path = Path("data/sessions")
    # Fernet key (urlsafe base64, 32 bytes). Required in production; generated in development.
    session_key: SecretStr | None = None
    session_ttl_days: int = Field(default=30, ge=1, le=365)
    session_history_turns: int = Field(default=3, ge=0, le=10)  # Q/A pairs given to the LLM

    @model_validator(mode="after")
    def _production_requirements(self) -> Self:
        if self.is_production and self.session_key is None:
            raise ValueError("LEGALAI_SESSION_KEY is required in production")
        key = self.gemini_api_key.get_secret_value().strip() if self.gemini_api_key else ""
        if self.llm_provider == "gemini" and not key:
            raise ValueError("LEGALAI_GEMINI_API_KEY is required when LEGALAI_LLM_PROVIDER=gemini")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


def load_settings() -> Settings:
    """Build settings from the current environment. Called once per app instance."""
    return Settings()
