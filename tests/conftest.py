"""Pytest fixtures: path setup, fakeredis, sample payloads."""

from __future__ import annotations

import hashlib
import hmac
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import fakeredis.aioredis
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
def api_client(monkeypatch, webhook_secret):
    """FastAPI TestClient with mocked arq + fakeredis async for delivery dedup."""
    from common import settings as settings_mod
    from common.settings import Settings

    settings_mod.get_settings.cache_clear()

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    enqueued: list[dict] = []

    class FakeJob:
        def __init__(self, job_id: str = "test-arq-job-1"):
            self.job_id = job_id

    class FakePool:
        async def enqueue_job(self, name: str, *args, **kwargs):
            payload = args[0] if args else kwargs
            enqueued.append({"name": name, "payload": payload})
            return FakeJob()

        async def close(self):
            pass

    fake_pool = FakePool()

    async def fake_claim(redis_url, delivery_id, *, prefix="pr-sentinel:delivery:", ttl=86400):
        if not delivery_id:
            return True
        key = f"{prefix}{delivery_id}"
        # SET NX semantics
        ok = await fake.set(key, "1", nx=True, ex=ttl)
        return bool(ok)

    async def fake_create_pool(_url):
        return fake_pool

    import main as api_main

    monkeypatch.setattr(api_main, "claim_delivery", fake_claim)
    monkeypatch.setattr(api_main, "create_arq_pool", fake_create_pool)
    monkeypatch.setattr(
        api_main,
        "get_settings",
        lambda: Settings(
            github_webhook_secret=webhook_secret,
            webhook_skip_verify=False,
            allow_insecure_webhooks=False,
            redis_url="redis://localhost:6379/0",
            use_fixtures=True,
        ),
    )
    # Pre-set pool so webhook does not need lifespan
    api_main._arq_pool = fake_pool

    from fastapi.testclient import TestClient

    with TestClient(api_main.app, raise_server_exceptions=True) as client:
        yield client, enqueued, fake

    api_main._arq_pool = None
    settings_mod.get_settings.cache_clear()
