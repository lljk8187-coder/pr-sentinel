"""M4 jobs API + console auth / retry tests."""

from __future__ import annotations

import json

import pytest


def test_health_ok(api_client):
    client, _, _ = api_client
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_get_jobs_no_admin_token_503(api_client):
    client, _, _ = api_client
    resp = client.get("/jobs")
    assert resp.status_code == 503
    assert "ADMIN_TOKEN" in resp.json()["detail"]


def test_get_jobs_wrong_token_403(api_client_admin, admin_token):
    client, _, _, _ = api_client_admin
    resp = client.get("/jobs", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 403


def test_get_jobs_bearer_ok(api_client_admin, admin_token, sign, sample_pr_payload):
    client, enqueued, fake, _ = api_client_admin
    body = json.dumps(sample_pr_payload).encode()
    r = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sign(body),
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-jobs-1",
        },
    )
    assert r.status_code == 202
    assert r.json().get("store_job_id")

    resp = client.get(
        "/jobs",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1
    job = data["jobs"][0]
    assert job["owner"] == "acme"
    assert job["repo"] == "demo"
    assert job["pr"] == 7
    assert job["status"] == "queued"
    assert job["delivery_id"] == "delivery-jobs-1"
    assert job["sha"].startswith("deadbeef")


def test_get_jobs_x_admin_token_header(api_client_admin, admin_token, sign, sample_pr_payload):
    client, _, _, _ = api_client_admin
    body = json.dumps(sample_pr_payload).encode()
    client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sign(body),
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-x-hdr",
        },
    )
    resp = client.get("/jobs", headers={"X-Admin-Token": admin_token})
    assert resp.status_code == 200
    assert resp.json()["count"] >= 1


def test_retry_auth_fail(api_client_admin, admin_token, sign, sample_pr_payload):
    client, enqueued, _, _ = api_client_admin
    body = json.dumps(sample_pr_payload).encode()
    r = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sign(body),
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-retry-auth",
        },
    )
    store_id = r.json()["store_job_id"]
    before = len(enqueued)

    resp = client.post(f"/jobs/{store_id}/retry")  # no token
    assert resp.status_code == 403
    assert len(enqueued) == before

    resp2 = client.post(
        f"/jobs/{store_id}/retry",
        headers={"Authorization": "Bearer wrong"},
    )
    assert resp2.status_code == 403
    assert len(enqueued) == before


def test_retry_success_mock(api_client_admin, admin_token, sign, sample_pr_payload):
    client, enqueued, _, _ = api_client_admin
    body = json.dumps(sample_pr_payload).encode()
    r = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sign(body),
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-retry-ok",
        },
    )
    assert r.status_code == 202
    store_id = r.json()["store_job_id"]
    before = len(enqueued)

    resp = client.post(
        f"/jobs/{store_id}/retry",
        headers={"X-Admin-Token": admin_token},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "queued"
    assert data["retried_from"] == store_id
    assert data["job"]["owner"] == "acme"
    assert len(enqueued) == before + 1
    assert enqueued[-1]["name"] == "process_pr"
    assert enqueued[-1]["payload"]["delivery_id"] == "delivery-retry-ok"


def test_retry_by_delivery_id(api_client_admin, admin_token, sign, sample_pr_payload):
    client, enqueued, _, _ = api_client_admin
    body = json.dumps(sample_pr_payload).encode()
    client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sign(body),
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-by-id",
        },
    )
    before = len(enqueued)
    resp = client.post(
        "/jobs/delivery-by-id/retry",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 202
    assert len(enqueued) == before + 1


def test_retry_missing_job_404(api_client_admin, admin_token):
    client, _, _, _ = api_client_admin
    resp = client.post(
        "/jobs/does-not-exist/retry",
        headers={"X-Admin-Token": admin_token},
    )
    assert resp.status_code == 404


def test_console_pages_render(api_client):
    client, _, _ = api_client
    r1 = client.get("/")
    assert r1.status_code == 200
    assert "GitHub App" in r1.text
    r2 = client.get("/console")
    assert r2.status_code == 200
    assert "最近任务" in r2.text
