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

    # Phase6 M24: webhook body size + Redis rate limit (no slowapi)
    webhook_max_body_bytes: int = 1_048_576  # 1 MiB
    webhook_rate_limit: int = 120
    webhook_rate_window_seconds: int = 60
    webhook_rate_limit_prefix: str = "pr-sentinel:webhook:rl:"

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


class LiveAuthError(RuntimeError):
    """Raised when USE_FIXTURES=false but App/PAT credentials are missing."""


def resolve_app_private_key(settings: "Settings") -> str:
    """Return PEM text from GITHUB_APP_PRIVATE_KEY or *_PATH; empty if unset."""
    inline = (settings.github_app_private_key or "").strip()
    if inline:
        return settings.github_app_private_key
    path = (settings.github_app_private_key_path or "").strip()
    if not path:
        return ""
    p = Path(path)
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8")


def validate_live_auth(settings: "Settings") -> None:
    """Fail-fast for live mode: require GitHub App or PAT; no silent fixtures.

    No-op when ``settings.use_fixtures`` is True.
    """
    if settings.use_fixtures:
        return

    has_pat = bool((settings.github_token or "").strip())
    has_app_id = bool((settings.github_app_id or "").strip())
    key_path = (settings.github_app_private_key_path or "").strip()
    inline_key = (settings.github_app_private_key or "").strip()
    key_path_bad = bool(key_path) and not Path(key_path).is_file()
    has_key = bool(inline_key) or (bool(key_path) and not key_path_bad)

    if has_pat or (has_app_id and has_key):
        return

    missing: list[str] = []
    if not has_pat:
        missing.append("GITHUB_TOKEN")
    if not has_app_id:
        missing.append("GITHUB_APP_ID")
    if not has_key:
        if key_path_bad:
            missing.append(
                f"GITHUB_APP_PRIVATE_KEY_PATH={key_path!r} (not a readable file)"
            )
        else:
            missing.append("GITHUB_APP_PRIVATE_KEY or GITHUB_APP_PRIVATE_KEY_PATH")

    raise LiveAuthError(
        "Live mode (USE_FIXTURES=false) requires GitHub credentials; "
        "silent fixtures fallback is disabled. Provide either:\n"
        "  - GITHUB_APP_ID + (GITHUB_APP_PRIVATE_KEY or GITHUB_APP_PRIVATE_KEY_PATH)\n"
        "  - or GITHUB_TOKEN (PAT)\n"
        f"Missing / invalid: {', '.join(missing)}"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
