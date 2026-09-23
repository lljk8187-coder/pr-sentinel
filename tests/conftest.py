"""Pytest fixtures: path setup, fakeredis, sample payloads."""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
from pathlib import Path

import fakeredis
import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "packages", ROOT / "packages" / "github", ROOT / "apps" / "api", ROOT / "apps" / "worker"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

FIXTURES = ROOT / "tests" / "fixtures"
SECRET = "test-webhook-secret"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def webhook_secret() -> str:
    return SECRET


@pytest.fixture
def sign():
    def _sign(body: bytes, secret: str = SECRET) -> str:
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    return _sign


@pytest.fixture
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def sample_pr_payload() -> dict:
    return {
        "action": "opened",
        "number": 7,
        "pull_request": {
            "number": 7,
            "html_url": "https://github.com/acme/demo/pull/7",
            "head": {"sha": "deadbeefcafebabe000011112222333344445555"},
        },
        "repository": {
            "full_name": "acme/demo",
            "name": "demo",
            "owner": {"login": "acme"},
        },
        "installation": {"id": 12345},
    }


@pytest.fixture
def api_client(monkeypatch, fake_redis, webhook_secret):
    """FastAPI TestClient with fakeredis + known secret."""
    from common import settings as settings_mod
    from common.settings import Settings

    settings_mod.get_settings.cache_clear()
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", webhook_secret)
    monkeypatch.setenv("WEBHOOK_SKIP_VERIFY", "false")
    monkeypatch.setenv("ALLOW_INSECURE_WEBHOOKS", "false")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("USE_FIXTURES", "true")

    # Re-import after env
    settings_mod.get_settings.cache_clear()

    import main as api_main
    from common.queue import JobQueue

    class FakeJobQueue(JobQueue):
        def __init__(self, redis_url: str, queue_key: str = "pr-sentinel:jobs"):
            self.queue_key = queue_key
            self._client = fake_redis

    monkeypatch.setattr(api_main, "JobQueue", FakeJobQueue)
    monkeypatch.setattr(api_main, "get_settings", lambda: Settings(
        github_webhook_secret=webhook_secret,
        webhook_skip_verify=False,
        allow_insecure_webhooks=False,
        redis_url="redis://localhost:6379/0",
        use_fixtures=True,
    ))

    from fastapi.testclient import TestClient

    with TestClient(api_main.app) as client:
        yield client, fake_redis

    settings_mod.get_settings.cache_clear()
