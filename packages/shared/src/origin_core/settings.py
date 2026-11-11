"""Process configuration, read from the environment (and `.env` in development)."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    DEMO = "demo"
    PRODUCTION = "production"


class ProviderMode(StrEnum):
    """How provider adapters reach the outside world.

    live:   call the provider; responses are cached.
    record: call the provider and also write each raw response to the fixtures directory.
    replay: never call out; serve recorded responses and fail if one is missing.
    """

    LIVE = "live"
    RECORD = "record"
    REPLAY = "replay"


class BlobBackend(StrEnum):
    S3 = "s3"
    FILESYSTEM = "filesystem"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

    env: Environment = Field(default=Environment.DEVELOPMENT, alias="ORIGIN_ENV")
    log_level: str = Field(default="INFO", alias="ORIGIN_LOG_LEVEL")
    log_json: bool = Field(default=False, alias="ORIGIN_LOG_JSON")

    database_url: str = Field(
        default="postgresql+asyncpg://origin:origin@127.0.0.1:5432/origin", alias="DATABASE_URL"
    )
    redis_url: str = Field(default="redis://127.0.0.1:6379/0", alias="REDIS_URL")

    blob_backend: BlobBackend = Field(default=BlobBackend.S3, alias="BLOB_BACKEND")
    blob_dir: Path = Field(default=Path("var/blobs"), alias="BLOB_DIR")
    s3_endpoint: str | None = Field(default="http://127.0.0.1:8333", alias="S3_ENDPOINT")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    s3_bucket: str = Field(default="origin", alias="S3_BUCKET")
    s3_access_key: str = Field(default="origin", alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="origin-dev-secret", alias="S3_SECRET_KEY")

    upload_max_bytes: int = Field(default=20_000_000, alias="ORIGIN_UPLOAD_MAX_BYTES", gt=0)
    upload_max_pixels: int = Field(default=50_000_000, alias="ORIGIN_UPLOAD_MAX_PIXELS", gt=0)
    # Requests per client per minute; 0 turns the limit off.
    rate_limit_uploads: int = Field(default=30, alias="ORIGIN_RATE_LIMIT_UPLOADS", ge=0)
    rate_limit_runs: int = Field(default=10, alias="ORIGIN_RATE_LIMIT_RUNS", ge=0)

    models_dir: Path = Field(default=Path("models"), alias="ORIGIN_MODELS_DIR")
    exiftool_path: str = Field(default="exiftool", alias="EXIFTOOL_PATH")

    provider_mode: ProviderMode = Field(default=ProviderMode.LIVE, alias="ORIGIN_PROVIDER_MODE")
    fixtures_dir: Path = Field(default=Path("fixtures/recordings"), alias="ORIGIN_FIXTURES_DIR")
    synthetic_fixtures_dir: Path = Field(
        default=Path("fixtures/synthetic"), alias="ORIGIN_SYNTHETIC_FIXTURES_DIR"
    )
    #: Reverse-image providers a trace uses, in order: vision, lens, yandex.
    providers: list[str] = Field(
        default_factory=lambda: ["vision", "lens"], alias="ORIGIN_PROVIDERS"
    )
    google_vision_api_key: SecretStr | None = Field(default=None, alias="GOOGLE_VISION_API_KEY")
    serpapi_api_key: SecretStr | None = Field(default=None, alias="SERPAPI_API_KEY")
    #: Which model extracts claims and groups narratives: gemini, ollama or anthropic.
    llm_provider: str = Field(default="gemini", alias="ORIGIN_LLM_PROVIDER")
    gemini_api_key: SecretStr | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-3.5-flash-lite", alias="ORIGIN_GEMINI_MODEL")
    ollama_url: str = Field(default="http://127.0.0.1:11434", alias="OLLAMA_URL")
    ollama_model: str = Field(default="qwen3:8b", alias="ORIGIN_OLLAMA_MODEL")
    anthropic_api_key: SecretStr | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-opus-5-5", alias="ORIGIN_ANTHROPIC_MODEL")
    enable_unofficial_providers: bool = Field(
        default=False, alias="ORIGIN_ENABLE_UNOFFICIAL_PROVIDERS"
    )

    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"], alias="ORIGIN_CORS_ORIGINS"
    )

    @model_validator(mode="after")
    def _guard_modes(self) -> Settings:
        if self.env is Environment.PRODUCTION and self.enable_unofficial_providers:
            raise ValueError(
                "ORIGIN_ENABLE_UNOFFICIAL_PROVIDERS must be false when ORIGIN_ENV=production: "
                "unofficial providers query engine front ends and may breach their terms."
            )
        if self.env is Environment.DEMO and self.provider_mode is not ProviderMode.REPLAY:
            raise ValueError("ORIGIN_ENV=demo requires ORIGIN_PROVIDER_MODE=replay.")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
