"""Application settings loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    github_webhook_secret: str = "change-me"
    webhook_skip_verify: bool = False
    allow_insecure_webhooks: bool = False

    redis_url: str = "redis://localhost:6379/0"
    queue_key: str = "pr-sentinel:jobs"

    github_token: str = ""
    github_app_id: str = ""
    github_app_private_key: str = ""
    github_app_private_key_path: str = ""

    use_fixtures: bool = False
    fixtures_dir: str = "tests/fixtures"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"

    @property
    def skip_webhook_verify(self) -> bool:
        return self.webhook_skip_verify or self.allow_insecure_webhooks

    def fixtures_path(self) -> Path:
        return Path(self.fixtures_dir)


@lru_cache
def get_settings() -> Settings:
    return Settings()
