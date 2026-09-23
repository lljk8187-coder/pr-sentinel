"""M13: check_run_url builder, console status counts, /metrics auth."""

from __future__ import annotations

import asyncio
import uuid

from common.job_store import (
    aggregate_status_counts,
    build_check_run_url,
    job_to_detail_dict,
    record_job,
    update_job_result,
)
from common import metrics as metrics_mod


def test_build_check_run_url_uses_runs_not_check_runs():
    url = build_check_run_url("acme", "demo", 987654321)
    assert url == "https://github.com/acme/demo/runs/987654321"
    assert "/runs/" in url
    assert "check-runs" not in url


def test_build_check_run_url_null_when_missing():
    assert build_check_run_url("acme", "demo", None) is None
    assert build_check_run_url(None, "demo", 1) is None
    assert build_check_run_url("acme", None, 1) is None
    assert build_check_run_url("", "demo", 1) is None


def test_job_to_detail_dict_includes_check_run_url():
    detail = job_to_detail_dict(
        {
            "id": "abc",
            "delivery_id": "d1",
            "owner": "acme",
            "repo": "demo",
            "pr": 7,
            "sha": "deadbeefcafebabe",
            "status": "success",
            "created_at": "t",
            "findings": [],
            "report_md": "# r",
            "check_run_id": 42,
            "updated_at": "t2",
        }
    )
    assert detail["check_run_id"] == 42
    assert detail["check_run_url"] == "https://github.com/acme/demo/runs/42"
    assert "check-runs" not in detail["check_run_url"]


def test_job_to_detail_dict_check_run_url_null_without_id():
    detail = job_to_detail_dict(
        {
            "id": "abc",
            "owner": "acme",
            "repo": "demo",
            "pr": 1,
            "sha": "x",
            "status": "queued",
            "created_at": "t",
            "findings": [],
            "check_run_id": None,
        }
    )
    assert detail["check_run_url"] is None


def test_aggregate_status_counts():
    jobs = [
        {"status": "queued"},
        {"status": "success"},
        {"status": "success"},
        {"status": "failed"},
        {},
    ]
    counts = aggregate_status_counts(jobs)
    assert counts["queued"] == 1
    assert counts["success"] == 2
    assert counts["failed"] == 1
    assert counts["unknown"] == 1


def test_get_job_detail_exposes_check_run_url(api_client_admin, admin_token, database_url):
    client, _, _, _ = api_client_admin

    async def _seed():
        payload = {
            "delivery_id": f"m13-url-{uuid.uuid4().hex[:8]}",
            "owner": "acme",
            "repo": "demo",
            "pr_number": 3,
            "head_sha": "aabbccddeeff00112233445566778899aabbccdd",
        }
        rec = await record_job(database_url, payload=payload, status="queued")
        await update_job_result(
            database_url,
            rec["id"],
            status="success",
            findings=[],
            report_md="# m13\n",
            check_run_id=123456789,
        )
        return rec["id"]

    job_id = asyncio.run(_seed())
    resp = client.get(f"/jobs/{job_id}", headers={"X-Admin-Token": admin_token})
    assert resp.status_code == 200
    data = resp.json()
    assert data["check_run_id"] == 123456789
    assert data["check_run_url"] == "https://github.com/acme/demo/runs/123456789"
    assert "/check-runs/" not in data["check_run_url"]


def test_console_job_detail_links_check_run(api_client_admin, admin_token, database_url):
    client, _, _, _ = api_client_admin

    async def _seed():
        payload = {
            "delivery_id": f"m13-html-{uuid.uuid4().hex[:8]}",
            "owner": "acme",
            "repo": "demo",
            "pr_number": 4,
            "head_sha": "11223344556677889900aabbccddeeff11223344",
        }
        rec = await record_job(database_url, payload=payload, status="success")
        await update_job_result(
            database_url,
            rec["id"],
            status="success",
            findings=[],
            report_md="# linked\n",
            check_run_id=555666777,
        )
        return rec["id"]

    job_id = asyncio.run(_seed())
    resp = client.get(f"/console/jobs/{job_id}")
    assert resp.status_code == 200
    assert "https://github.com/acme/demo/runs/555666777" in resp.text
    assert "check-runs" not in resp.text


def test_console_shows_status_counts(api_client_admin, admin_token, database_url):
    client, _, _, _ = api_client_admin

    async def _seed():
        for status in ("queued", "success", "failed"):
            payload = {
                "delivery_id": f"m13-cnt-{status}-{uuid.uuid4().hex[:6]}",
                "owner": "acme",
                "repo": "demo",
                "pr_number": 1,
                "head_sha": uuid.uuid4().hex + "abcd",
            }
            await record_job(database_url, payload=payload, status=status)

    asyncio.run(_seed())
    resp = client.get("/console")
    assert resp.status_code == 200
    assert "状态概览" in resp.text
    assert "success" in resp.text
    assert "/metrics" in resp.text


def test_metrics_no_admin_503(api_client):
    client, _, _ = api_client
    metrics_mod.reset_for_tests()
    resp = client.get("/metrics")
    assert resp.status_code == 503
    assert "ADMIN_TOKEN" in resp.json()["detail"]


def test_metrics_wrong_token_403(api_client_admin, admin_token):
    client, _, _, _ = api_client_admin
    resp = client.get("/metrics", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 403


def test_metrics_ok_and_webhook_increments(
    api_client_admin, admin_token, sign, sample_pr_payload
):
    import json

    client, _, _, _ = api_client_admin
    metrics_mod.reset_for_tests()
    body = json.dumps(sample_pr_payload).encode()
    delivery = f"m13-dup-{uuid.uuid4().hex[:8]}"
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": sign(body),
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery,
    }
    assert client.post("/webhooks/github", content=body, headers=headers).status_code == 202
    assert client.post("/webhooks/github", content=body, headers=headers).status_code == 200

    resp = client.get("/metrics", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    counters = resp.json()["counters"]
    assert counters["webhook_accepted"] >= 1
    assert counters["webhook_duplicate"] >= 1
    assert "worker_success" in counters
    assert "worker_fail" in counters
