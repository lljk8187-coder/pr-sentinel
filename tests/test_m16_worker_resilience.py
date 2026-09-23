"""M16: worker resilience — arq Retry vs exhausted transient vs non-transient."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import httpx
import pytest
from arq import Retry

ROOT = Path(__file__).resolve().parents[1]


def _load_worker_main():
    path = ROOT / "apps" / "worker" / "main.py"
    spec = importlib.util.spec_from_file_location("pr_sentinel_worker_main_m16", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    for pth in (ROOT, ROOT / "packages", ROOT / "packages" / "github"):
        sp = str(pth)
        if sp not in sys.path:
            sys.path.insert(0, sp)
    spec.loader.exec_module(mod)
    return mod


def _http_status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://api.github.com/repos/acme/demo/pulls/7/files")
    resp = httpx.Response(code, request=req)
    return httpx.HTTPStatusError(f"{code} boom", request=req, response=resp)


def _job() -> dict:
    return {
        "owner": "acme",
        "repo": "demo",
        "pr_number": 7,
        "head_sha": "deadbeefcafebabe000011112222333344445555",
        "installation_id": 12345,
        "delivery_id": "delivery-m16",
    }


@pytest.fixture
def worker_mod():
    return _load_worker_main()


@pytest.fixture
def status_calls():
    return []


async def _run_process_pr(worker_mod, monkeypatch, status_calls, *, job_try: int, exc: BaseException):
    async def fake_update(database_url, job, status, error=None, findings=None, report_md=None, check_run_id=None):
        status_calls.append({"status": status, "error": error})
        return True

    monkeypatch.setattr(
        worker_mod,
        "update_job_status_by_payload",
        fake_update,
    )
    monkeypatch.setattr(
        worker_mod,
        "process_job",
        lambda *a, **k: (_ for _ in ()).throw(exc),
    )
    # Avoid real metrics side effects leaking across tests
    monkeypatch.setattr(worker_mod.metrics_mod, "incr", lambda *a, **k: None)

    ctx = {"settings": type("S", (), {"database_url": "postgresql://unused"})(), "job_try": job_try}
    return await worker_mod.process_pr(ctx, _job())


@pytest.mark.asyncio
async def test_transient_middle_try_raises_retry(worker_mod, monkeypatch, status_calls):
    """429 / 5xx with job_try < max_tries → optional retrying error, then Retry."""
    with pytest.raises(Retry) as ei:
        await _run_process_pr(
            worker_mod,
            monkeypatch,
            status_calls,
            job_try=1,
            exc=_http_status_error(429),
        )
    assert ei.value.defer_score == 5000  # 5s in ms
    # running (initial) + retrying hint
    assert any(c["status"] == "running" and c["error"] and "retrying try=1" in c["error"] for c in status_calls)
    assert not any(c["status"] == "failed" for c in status_calls)


@pytest.mark.asyncio
async def test_transient_exhausted_marks_failed_no_retry(worker_mod, monkeypatch, status_calls):
    """Same transient on last try → failed with transient exhausted, return (no Retry)."""
    result = await _run_process_pr(
        worker_mod,
        monkeypatch,
        status_calls,
        job_try=3,
        exc=_http_status_error(503),
    )
    assert result["_action"] == "failed"
    assert "transient exhausted" in result["error"]
    failed = [c for c in status_calls if c["status"] == "failed"]
    assert len(failed) == 1
    assert failed[0]["error"] is not None
    assert failed[0]["error"].startswith("transient exhausted:")
    assert len(failed[0]["error"]) <= 500


@pytest.mark.asyncio
async def test_transient_timeout_exhausted(worker_mod, monkeypatch, status_calls):
    """Network timeout on last try also exhausts without raising Retry."""
    result = await _run_process_pr(
        worker_mod,
        monkeypatch,
        status_calls,
        job_try=3,
        exc=httpx.ReadTimeout("read timed out"),
    )
    assert result["_action"] == "failed"
    assert any(c["status"] == "failed" and "transient exhausted" in (c["error"] or "") for c in status_calls)


@pytest.mark.asyncio
async def test_non_transient_4xx_fails_immediately(worker_mod, monkeypatch, status_calls):
    """Non-429 4xx → immediate failed status, no Retry."""
    with pytest.raises(httpx.HTTPStatusError):
        await _run_process_pr(
            worker_mod,
            monkeypatch,
            status_calls,
            job_try=1,
            exc=_http_status_error(404),
        )
    failed = [c for c in status_calls if c["status"] == "failed"]
    assert len(failed) == 1
    assert "404" in (failed[0]["error"] or "")
    assert not any(c["error"] and "retrying" in c["error"] for c in status_calls)
    assert not any(c["error"] and "transient exhausted" in c["error"] for c in status_calls)


@pytest.mark.asyncio
async def test_transient_second_try_defer_backoff(worker_mod, monkeypatch, status_calls):
    """job_try=2 → defer=10, still raises Retry."""
    with pytest.raises(Retry) as ei:
        await _run_process_pr(
            worker_mod,
            monkeypatch,
            status_calls,
            job_try=2,
            exc=_http_status_error(500),
        )
    assert ei.value.defer_score == 10000  # 10s in ms


def test_is_transient_http_matrix(worker_mod):
    assert worker_mod._is_transient_http(_http_status_error(429))
    assert worker_mod._is_transient_http(_http_status_error(500))
    assert worker_mod._is_transient_http(_http_status_error(503))
    assert worker_mod._is_transient_http(httpx.ConnectTimeout("x"))
    assert not worker_mod._is_transient_http(_http_status_error(400))
    assert not worker_mod._is_transient_http(_http_status_error(401))
    assert not worker_mod._is_transient_http(_http_status_error(404))
    assert not worker_mod._is_transient_http(_http_status_error(422))
    assert not worker_mod._is_transient_http(ValueError("nope"))


def test_worker_settings_max_tries_unchanged(worker_mod):
    assert worker_mod.WorkerSettings.max_tries == 3
    assert worker_mod.WorkerSettings.retry_jobs is True
