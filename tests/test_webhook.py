"""Webhook HMAC + enqueue tests."""

from __future__ import annotations

import json


def test_signature_ok_enqueues(api_client, sign, sample_pr_payload):
    client, fake_redis = api_client
    body = json.dumps(sample_pr_payload).encode()
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sign(body),
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-1",
        },
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "queued"
    assert data["job"]["pr_number"] == 7
    assert data["job"]["head_sha"].startswith("deadbeef")

    items = fake_redis.lrange("pr-sentinel:jobs", 0, -1)
    assert len(items) == 1
    job = json.loads(items[0])
    assert job["owner"] == "acme"
    assert job["repo"] == "demo"
    assert job["installation_id"] == 12345


def test_signature_fail_401(api_client, sample_pr_payload):
    client, _ = api_client
    body = json.dumps(sample_pr_payload).encode()
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=deadbeef",
            "X-GitHub-Event": "pull_request",
        },
    )
    assert resp.status_code == 401


def test_non_target_event_ignored(api_client, sign, sample_pr_payload):
    client, fake_redis = api_client
    sample_pr_payload["action"] = "closed"
    body = json.dumps(sample_pr_payload).encode()
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sign(body),
            "X-GitHub-Event": "pull_request",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    assert fake_redis.llen("pr-sentinel:jobs") == 0


def test_synchronize_enqueues(api_client, sign, sample_pr_payload):
    client, fake_redis = api_client
    sample_pr_payload["action"] = "synchronize"
    body = json.dumps(sample_pr_payload).encode()
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sign(body),
            "X-GitHub-Event": "pull_request",
        },
    )
    assert resp.status_code == 202
    assert fake_redis.llen("pr-sentinel:jobs") == 1


def test_verify_signature_unit(webhook_secret, sign):
    from main import verify_signature

    body = b'{"ok":true}'
    assert verify_signature(webhook_secret, body, sign(body))
    assert not verify_signature(webhook_secret, body, "sha256=00")
    assert not verify_signature(webhook_secret, body, None)
