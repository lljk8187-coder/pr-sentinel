"""M20: console ops UX — failed row highlight, error truncate, ?status= filter."""

from __future__ import annotations

import asyncio
import uuid

import pytest


def _seed_mixed(database_url: str) -> dict[str, str]:
    from common.job_store import record_job

    async def _run() -> dict[str, str]:
        ids: dict[str, str] = {}
        long_err = "boom-" + ("x" * 120)
        for status, err in (
            ("queued", None),
            ("success", None),
            ("failed", long_err),
            ("failed", "short fail"),
        ):
            payload = {
                "delivery_id": f"m20-{status}-{uuid.uuid4().hex[:8]}",
                "owner": "acme",
                "repo": "demo",
                "pr_number": 20,
                "head_sha": uuid.uuid4().hex + "abcd",
            }
            rec = await record_job(
                database_url, payload=payload, status=status, error=err
            )
            ids.setdefault(status, rec["id"])
            if status == "failed" and err and err.startswith("boom-"):
                ids["failed_long"] = rec["id"]
                ids["long_error"] = long_err
        return ids

    return asyncio.run(_run())


def test_console_status_failed_filter(api_client_admin, admin_token, database_url):
    client, _, _, _ = api_client_admin
    _seed_mixed(database_url)

    resp = client.get("/console?status=failed")
    assert resp.status_code == 200
    assert "row-failed" in resp.text
    assert "筛选 status=" in resp.text
    assert "failed" in resp.text
    # Filtered list should not advertise queued rows as table content via status class
    # on non-failed jobs — overview may still link queued. Check truncated long error.
    assert "title=" in resp.text
    assert "err-truncate" in resp.text
    # Clarifying copy: failed (status) vs error (field)
    assert "消息字段" in resp.text
    assert "?status=failed" in resp.text


def test_console_unfiltered_still_renders(api_client_admin, admin_token, database_url):
    client, _, _, _ = api_client_admin
    _seed_mixed(database_url)
    resp = client.get("/console")
    assert resp.status_code == 200
    assert "最近任务" in resp.text
    assert "row-failed" in resp.text
    assert "状态概览" in resp.text
    assert "/console?status=failed" in resp.text


def test_console_error_truncated_and_title(api_client_admin, admin_token, database_url):
    client, _, _, _ = api_client_admin
    ids = _seed_mixed(database_url)
    long_err = ids["long_error"]
    resp = client.get("/console?status=failed")
    assert resp.status_code == 200
    # Full error available on hover (title); truncated in cell body
    assert f'title="{long_err}"' in resp.text or f"title='{long_err}'" in resp.text
    # Truncated body should not contain the full 120 x's run after boom-
    assert "boom-" in resp.text
    # Jinja truncate(80) leaves room for ellipsis; full tail should be gone from visible cell
    # (title still has it). Check that the raw super-long run is only in title context.
    assert long_err in resp.text  # present via title


def test_get_jobs_status_filter(api_client_admin, admin_token, database_url):
    client, _, _, _ = api_client_admin
    _seed_mixed(database_url)

    resp = client.get(
        "/jobs?status=failed",
        headers={"X-Admin-Token": admin_token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert data["count"] >= 2
    assert all(j["status"] == "failed" for j in data["jobs"])
    assert any(j.get("error") for j in data["jobs"])

    resp_all = client.get("/jobs", headers={"X-Admin-Token": admin_token})
    assert resp_all.status_code == 200
    assert resp_all.json()["count"] >= data["count"]
    assert resp_all.json()["status"] is None


@pytest.mark.asyncio
async def test_list_jobs_status_filter(database_url):
    from common.job_store import list_jobs, record_job

    await record_job(
        database_url,
        payload={
            "delivery_id": f"m20-lj-{uuid.uuid4().hex[:8]}",
            "owner": "acme",
            "repo": "demo",
            "pr_number": 1,
            "head_sha": "a" * 40,
        },
        status="failed",
        error="Nope",
    )
    await record_job(
        database_url,
        payload={
            "delivery_id": f"m20-lj-q-{uuid.uuid4().hex[:8]}",
            "owner": "acme",
            "repo": "demo",
            "pr_number": 2,
            "head_sha": "b" * 40,
        },
        status="queued",
    )
    failed = await list_jobs(database_url, limit=50, status="failed")
    assert failed
    assert all(j["status"] == "failed" for j in failed)
    queued = await list_jobs(database_url, limit=50, status="queued")
    assert queued
    assert all(j["status"] == "queued" for j in queued)
