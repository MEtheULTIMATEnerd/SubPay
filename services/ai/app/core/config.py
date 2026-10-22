"""AI service settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Load .env from the AI service root (two levels up from this file)
    # env_file is relative to the file location when using BaseSettings
    model_config = SettingsConfigDict(
        env_prefix="AI_",
        extra="ignore",
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
    )

    environment: str = "development"
    version: str = "0.1.0"
    provider_mode: str = "mock"

    # Vision provider selection: "mock", "openrouter", or "openai"
    vision_provider: str = "mock"

    # OpenRouter configuration
    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openai/gpt-4o-mini"

    # OpenAI configuration
    openai_api_key: SecretStr = SecretStr("")
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    # Request timeout in seconds for vision analysis calls
    vision_timeout_seconds: float = 30.0
    local_vision_enabled: bool = False
    local_access_token: SecretStr = SecretStr("")


@lru_cache
def get_settings() -> Settings:
    return Settings()
