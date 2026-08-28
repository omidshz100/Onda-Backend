from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ONDA_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Onda API"
    environment: Literal["development", "test", "production"] = "development"
    enable_docs: bool = False
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://onda:onda@127.0.0.1:5432/onda"

    api_jwt_secret: str = Field(default="development-only-secret-change-me-123456", min_length=32)
    api_jwt_algorithm: str = "HS256"
    access_token_minutes: int = Field(default=15, ge=5, le=60)
    refresh_token_days: int = Field(default=30, ge=1, le=90)

    jitsi_app_id: str = "onda"
    jitsi_app_secret: str = Field(default="development-jitsi-secret-change-me", min_length=24)
    jitsi_base_url: AnyHttpUrl = "https://meet.example.com"
    jitsi_token_minutes: int = Field(default=5, ge=1, le=15)

    apns_key_id: str | None = None
    apns_team_id: str | None = None
    apns_bundle_id: str | None = None
    apns_private_key: str | None = None

    auth_rate_limit_per_minute: int = Field(default=20, ge=5, le=500)
    call_ring_timeout_seconds: int = Field(default=45, ge=15, le=120)

    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]

    @model_validator(mode="after")
    def require_production_secrets(self) -> "Settings":
        apns_values = [
            self.apns_key_id,
            self.apns_team_id,
            self.apns_bundle_id,
            self.apns_private_key,
        ]
        if any(apns_values) and not all(apns_values):
            raise ValueError("All APNs credentials must be configured together")
        if self.environment == "production":
            if "development" in self.api_jwt_secret or "change-me" in self.api_jwt_secret:
                raise ValueError("A production API JWT secret is required")
            if "development" in self.jitsi_app_secret or "change-me" in self.jitsi_app_secret:
                raise ValueError("A production Jitsi secret is required")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
