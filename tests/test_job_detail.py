"""M9: job detail API + findings writeback into Postgres."""

from __future__ import annotations

import asyncio
import uuid

import pytest


@pytest.mark.asyncio
async def test_update_job_result_writes_findings(database_url):
    from common.job_store import (
        get_job,
        record_job,
        update_job_result,
        update_job_status_by_payload,
    )

    payload = {
        "delivery_id": f"m9-write-{uuid.uuid4().hex[:8]}",
        "owner": "acme",
        "repo": "demo",
        "pr_number": 42,
        "head_sha": "abc123def456",
    }
    recorded = await record_job(database_url, payload=payload, status="queued")
    job_id = recorded["id"]

    findings = [
        {
            "rule_id": "secrets",
            "severity": "high",
            "message": "possible secret",
            "title": "possible secret",
            "path": "cfg.env",
            "filename": "cfg.env",
            "line": 3,
            "detail": "AWS key pattern",
            "source": "rules",
            "meta": {},
        }
    ]
    report = "# PR Sentinel\n\n- high: possible secret\n"
    ok = await update_job_result(
        database_url,
        job_id,
        status="success",
        findings=findings,
        report_md=report,
        check_run_id=987654321,
    )
    assert ok is True

    row = await get_job(database_url, job_id)
    assert row is not None
    assert row["status"] == "success"
    assert row["report_md"] == report
    assert row["check_run_id"] == 987654321
    assert isinstance(row["findings"], list)
    assert row["findings"][0]["severity"] == "high"
    assert row["findings"][0]["path"] == "cfg.env"

    # Worker-style path: update_job_status_by_payload with matching payload
    ok2 = await update_job_status_by_payload(
        database_url,
        payload,
        "success",
        findings=[{"severity": "info", "title": "note", "message": "note", "path": None}],
        report_md="# updated\n",
        check_run_id=111,
    )
    assert ok2 is True
    row2 = await get_job(database_url, job_id)
    assert row2["check_run_id"] == 111
    assert row2["report_md"] == "# updated\n"
    assert row2["findings"][0]["severity"] == "info"


def test_get_job_detail_no_admin_503(api_client):
    client, _, _ = api_client
    fake_id = str(uuid.uuid4())
    resp = client.get(f"/jobs/{fake_id}")
    assert resp.status_code == 503
    assert "ADMIN_TOKEN" in resp.json()["detail"]


def test_get_job_detail_wrong_token_403(api_client_admin, admin_token):
    client, _, _, _ = api_client_admin
    fake_id = str(uuid.uuid4())
    resp = client.get(f"/jobs/{fake_id}", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 403


def test_get_job_detail_unknown_404(api_client_admin, admin_token):
    client, _, _, _ = api_client_admin
    fake_id = str(uuid.uuid4())
    resp = client.get(
        f"/jobs/{fake_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404


def test_get_job_detail_happy_with_findings(api_client_admin, admin_token, database_url):
    from common.job_store import record_job, update_job_result

    client, _, _, _ = api_client_admin

    async def _seed():
        payload = {
            "delivery_id": f"m9-detail-{uuid.uuid4().hex[:8]}",
            "owner": "acme",
            "repo": "demo",
            "pr_number": 7,
            "head_sha": "deadbeefcafebabe000011112222333344445555",
        }
        rec = await record_job(database_url, payload=payload, status="queued")
        await update_job_result(
            database_url,
            rec["id"],
            status="success",
            findings=[
                {
                    "severity": "error",
                    "title": "secret in patch",
                    "message": "secret in patch",
                    "path": "a.py",
                    "line": 10,
                    "detail": "AKIA...",
                }
            ],
            report_md="## Report\n\nOK-ish\n",
            check_run_id=555,
        )
        return rec["id"]

    job_id = asyncio.run(_seed())

    resp = client.get(
        f"/jobs/{job_id}",
        headers={"X-Admin-Token": admin_token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == job_id
    assert data["status"] == "success"
    assert data["owner"] == "acme"
    assert data["repo"] == "demo"
    assert data["pr"] == 7
    assert data["sha"].startswith("deadbeef")
    assert data["delivery_id"].startswith("m9-detail-")
    assert data["check_run_id"] == 555
    assert data["report_md"].startswith("## Report")
    assert len(data["findings"]) == 1
    assert data["findings"][0]["severity"] == "error"
    assert data["findings"][0]["path"] == "a.py"
    assert "payload" not in data  # detail view omits huge raw payload


def test_console_job_detail_page(api_client_admin, admin_token, database_url):
    from common.job_store import record_job, update_job_result

    client, _, _, _ = api_client_admin

    async def _seed():
        payload = {
            "delivery_id": f"m9-html-{uuid.uuid4().hex[:8]}",
            "owner": "acme",
            "repo": "demo",
            "pr_number": 9,
            "head_sha": "ffffffffffffffffffffffffffffffffffffffff",
        }
        rec = await record_job(database_url, payload=payload, status="success")
        await update_job_result(
            database_url,
            rec["id"],
            status="success",
            findings=[{"severity": "warning", "title": "large", "message": "large", "path": "bin.dat"}],
            report_md="# Hello M9\n",
        )
        return rec["id"]

    job_id = asyncio.run(_seed())
    resp = client.get(f"/console/jobs/{job_id}")
    assert resp.status_code == 200
    assert "任务详情" in resp.text
    assert "Hello M9" in resp.text
    assert "bin.dat" in resp.text
    assert "Postgres" in resp.text or "findings" in resp.text.lower()

    list_resp = client.get("/console")
    assert list_resp.status_code == 200
    assert "Postgres" in list_resp.text
    assert f"/console/jobs/{job_id}" in list_resp.text


def test_process_job_puts_findings_on_out(fixtures_dir):
    """process_job out dict includes findings list + report for writeback."""
    import importlib.util
    import sys
    from pathlib import Path

    from common.settings import Settings

    root = Path(__file__).resolve().parents[1]
    path = root / "apps" / "worker" / "main.py"
    spec = importlib.util.spec_from_file_location("pr_sentinel_worker_main_m9", path)
    assert spec and spec.loader
    worker_main = importlib.util.module_from_spec(spec)
    for pth in (root, root / "packages", root / "packages" / "github"):
        sp = str(pth)
        if sp not in sys.path:
            sys.path.insert(0, sp)
    spec.loader.exec_module(worker_main)

    settings = Settings(
        use_fixtures=True,
        fixtures_dir=str(fixtures_dir),
        github_token="",
    )
    job = {
        "owner": "acme",
        "repo": "demo",
        "pr_number": 7,
        "head_sha": "deadbeefcafebabe000011112222333344445555",
        "installation_id": None,
    }
    out = worker_main.process_job(job, settings)
    assert "report" in out
    assert isinstance(out.get("findings"), list)
