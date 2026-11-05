from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:9b"
    ollama_timeout_seconds: float = Field(default=300, gt=0, le=900)
    ollama_num_ctx: int = Field(default=8192, ge=2048, le=32768)
    ollama_num_predict: int = Field(default=2200, ge=256, le=8192)
    ollama_keep_alive: str = "5m"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)


@lru_cache
def get_settings() -> Settings:
    return Settings()
