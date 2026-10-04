"""Application settings, read from environment variables or services/api/.env."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=API_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"

    # Supabase
    supabase_url: str = ""
    supabase_anon_key: str = ""
    # Bypasses Row Level Security. Server-side only, and only for deliberate jobs.
    supabase_service_role_key: SecretStr = SecretStr("")
    # Legacy HS256 projects only. Leave empty when the project uses JWT signing keys.
    supabase_jwt_secret: SecretStr = SecretStr("")
    # The `aud` claim Supabase Auth puts in a signed-in user's access token.
    supabase_jwt_audience: str = "authenticated"

    # Comma-separated list of allowed web origins.
    cors_origins: str = "http://localhost:3000"

    ai_service_url: str = "http://localhost:8001"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

    @property
    def supabase_base_url(self) -> str:
        return self.supabase_url.strip().rstrip("/")

    @property
    def supabase_jwt_issuer(self) -> str:
        return f"{self.supabase_base_url}/auth/v1" if self.supabase_base_url else ""

    @property
    def supabase_jwks_url(self) -> str:
        if not self.supabase_base_url:
            return ""
        return f"{self.supabase_base_url}/auth/v1/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
