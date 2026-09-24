"""Phase6 M24: webhook body size limit + Redis rate limit."""

from __future__ import annotations

import json

import pytest


def _post_pr(client, sign, payload, delivery: str, *, body: bytes | None = None):
    raw = body if body is not None else json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": sign(raw),
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery,
    }
    return client.post("/webhooks/github", content=raw, headers=headers)


def test_oversized_body_413_not_enqueued(api_client_admin, sign, sample_pr_payload, monkeypatch):
    client, enqueued, _fake, _settings = api_client_admin
    import main as api_main

    monkeypatch.setattr(
        api_main,
        "get_settings",
        lambda: _settings(webhook_max_body_bytes=100),
    )
    # Body larger than 100 bytes; 413 is before HMAC
    body = b"x" * 200
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sign(body),
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "m24-big-body",
        },
    )
    assert resp.status_code == 413
    assert resp.json()["detail"] == "payload too large"
    assert len(enqueued) == 0


def test_content_length_over_limit_413(api_client_admin, sign, monkeypatch):
    """Content-Length > max → 413 without enqueue (checked before HMAC)."""
    client, enqueued, _fake, _settings = api_client_admin
    import main as api_main

    monkeypatch.setattr(
        api_main,
        "get_settings",
        lambda: _settings(webhook_max_body_bytes=50),
    )
    body = b"y" * 80
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "X-Hub-Signature-256": "sha256=00",
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "m24-cl",
        },
    )
    assert resp.status_code == 413
    assert resp.json()["detail"] == "payload too large"
    assert len(enqueued) == 0


def test_rate_limit_429_fourth_request(api_client_admin, sign, sample_pr_payload, monkeypatch):
    client, enqueued, _fake, _settings = api_client_admin
    import main as api_main

    monkeypatch.setattr(
        api_main,
        "get_settings",
        lambda: _settings(
            webhook_rate_limit=3,
            webhook_rate_limit_prefix="pr-sentinel:webhook:rl:m24-test:",
        ),
    )
    statuses = []
    for i in range(4):
        resp = _post_pr(client, sign, sample_pr_payload, f"m24-rl-{i}")
        statuses.append(resp.status_code)

    assert statuses[:3] == [202, 202, 202]
    assert statuses[3] == 429
    assert len(enqueued) == 3

    resp5 = _post_pr(client, sign, sample_pr_payload, "m24-rl-5")
    assert resp5.status_code == 429
    assert resp5.json()["detail"] == "rate limit exceeded"
    assert len(enqueued) == 3


def test_normal_webhook_still_202(api_client, sign, sample_pr_payload):
    """Regression: defaults allow normal signed PR webhook."""
    client, enqueued, _fake = api_client
    resp = _post_pr(client, sign, sample_pr_payload, "m24-ok")
    assert resp.status_code == 202
    assert resp.json()["status"] == "queued"
    assert len(enqueued) == 1


@pytest.mark.asyncio
async def test_check_webhook_rate_limit_unit(monkeypatch):
    """Direct INCR+EXPIRE behaviour + fail-open on Redis error."""
    import fakeredis.aioredis

    import common.queue as queue_mod
    from common.queue import check_webhook_rate_limit

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    class _NoClose:
        """Wrap FakeRedis so check_webhook_rate_limit's aclose is a no-op."""

        def __init__(self, inner):
            self._inner = inner

        async def incr(self, key):
            return await self._inner.incr(key)

        async def expire(self, key, seconds):
            return await self._inner.expire(key, seconds)

        async def aclose(self):
            return None

    monkeypatch.setattr(
        queue_mod.redis_async,
        "from_url",
        lambda *_a, **_k: _NoClose(fake),
    )
    assert await check_webhook_rate_limit("redis://x", "ip1", limit=2, prefix="t:")
    assert await check_webhook_rate_limit("redis://x", "ip1", limit=2, prefix="t:")
    assert not await check_webhook_rate_limit("redis://x", "ip1", limit=2, prefix="t:")

    class Boom:
        async def incr(self, *_a, **_k):
            raise RuntimeError("redis down")

        async def aclose(self):
            pass

    monkeypatch.setattr(queue_mod.redis_async, "from_url", lambda *_a, **_k: Boom())
    assert await check_webhook_rate_limit("redis://x", "ip2", limit=1, prefix="t:") is True

    await fake.aclose()
