"""Webhook HMAC + arq enqueue + delivery dedup tests."""

from __future__ import annotations

import json


def test_signature_ok_enqueues(api_client, sign, sample_pr_payload):
    client, enqueued, _fake = api_client
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
    assert len(enqueued) == 1
    assert enqueued[0]["name"] == "process_pr"
    assert enqueued[0]["payload"]["owner"] == "acme"
    assert enqueued[0]["payload"]["installation_id"] == 12345


def test_signature_fail_401(api_client, sample_pr_payload):
    client, enqueued, _ = api_client
    body = json.dumps(sample_pr_payload).encode()
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=deadbeef",
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-bad",
        },
    )
    assert resp.status_code == 401
    assert len(enqueued) == 0


def test_non_target_event_ignored(api_client, sign, sample_pr_payload):
    client, enqueued, _ = api_client
    sample_pr_payload["action"] = "closed"
    body = json.dumps(sample_pr_payload).encode()
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sign(body),
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-closed",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    assert len(enqueued) == 0


def test_synchronize_enqueues(api_client, sign, sample_pr_payload):
    client, enqueued, _ = api_client
    sample_pr_payload["action"] = "synchronize"
    body = json.dumps(sample_pr_payload).encode()
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sign(body),
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-sync",
        },
    )
    assert resp.status_code == 202
    assert len(enqueued) == 1


def test_duplicate_delivery_not_reenqueued(api_client, sign, sample_pr_payload):
    client, enqueued, _ = api_client
    body = json.dumps(sample_pr_payload).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": sign(body),
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": "delivery-dup",
    }
    r1 = client.post("/webhooks/github", content=body, headers=headers)
    r2 = client.post("/webhooks/github", content=body, headers=headers)
    assert r1.status_code == 202
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"
    assert len(enqueued) == 1


def test_verify_signature_unit(webhook_secret, sign):
    from main import verify_signature

    body = b'{"ok":true}'
    assert verify_signature(webhook_secret, body, sign(body))
    assert not verify_signature(webhook_secret, body, "sha256=00")
    assert not verify_signature(webhook_secret, body, None)
