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
    # Phase2 M5: jobs archive (Postgres via asyncpg)
    database_url: str = "postgresql://prsentinel:prsentinel@localhost:5432/prsentinel"
    # Delivery dedup key prefix + TTL (seconds)
    delivery_dedup_prefix: str = "pr-sentinel:delivery:"
    delivery_dedup_ttl: int = 86400 * 7  # 7 days

    # Auth: production prefers GitHub App; local/PAT is fallback
    github_token: str = ""
    github_app_id: str = ""
    github_app_private_key: str = ""
    github_app_private_key_path: str = ""

    use_fixtures: bool = False
    fixtures_dir: str = "tests/fixtures"

    # Diff truncation (also mirrored in defaults.DEFAULT_CONFIG)
    diff_max_pages: int = 5
    diff_per_page: int = 100
    diff_max_files: int = 300

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"

    # OpenAI-compatible LLM (optional; missing key → soft-skip LLM)
    openai_api_key: str = ""
    pr_sentinel_openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = ""

    # M4 console / jobs API auth (empty → write endpoints return 503)
    admin_token: str = ""
    jobs_list_max: int = 100

    @property
    def skip_webhook_verify(self) -> bool:
        return self.webhook_skip_verify or self.allow_insecure_webhooks

    def fixtures_path(self) -> Path:
        return Path(self.fixtures_dir)


@lru_cache
def get_settings() -> Settings:
    return Settings()
