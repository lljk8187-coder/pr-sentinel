"""FastAPI webhook receiver + M5/M9 console / jobs API (Postgres job store)."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Form, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

_ROOT = Path(__file__).resolve().parents[2]
for p in (_ROOT, _ROOT / "packages", _ROOT / "packages" / "github"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from common.job_store import (  # noqa: E402
    aggregate_status_counts,
    get_job,
    job_to_detail_dict,
    list_jobs,
    record_job,
    resolve_job,
)
from common import logutil  # noqa: E402
from common import metrics as metrics_mod  # noqa: E402
from common.queue import (  # noqa: E402
    check_webhook_rate_limit,
    claim_delivery,
    create_arq_pool,
    enqueue_process_pr,
)
from common.settings import Settings, get_settings  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pr-sentinel.api")

TARGET_ACTIONS = {"opened", "synchronize"}
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Injected in tests; production uses lifespan pool
_arq_pool = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _arq_pool
    settings = get_settings()
    try:
        _arq_pool = await create_arq_pool(settings.redis_url)
        logger.info("arq pool ready (%s)", settings.redis_url)
    except Exception:
        logger.exception("arq pool init failed — enqueue will retry/fail per request")
        _arq_pool = None
    yield
    if _arq_pool is not None:
        await _arq_pool.close()
        _arq_pool = None


app = FastAPI(
    title="pr-sentinel",
    version="1.3.0",
    description="Phase8 1.3.0: output & console M30–M32 (merge_findings, sticky clamp/severity sort, job detail source/rule_id; real App e2e optional)",
    lifespan=lifespan,
)


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Verify X-Hub-Signature-256 (sha256=<hex>). Always required unless skip switch."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = signature_header.removeprefix("sha256=")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, expected)


def extract_job_payload(event: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if event != "pull_request":
        return None
    action = payload.get("action")
    if action not in TARGET_ACTIONS:
        return None
    pr = payload.get("pull_request") or {}
    repo = payload.get("repository") or {}
    full_name = repo.get("full_name") or ""
    if "/" in full_name:
        owner, name = full_name.split("/", 1)
    else:
        owner = (repo.get("owner") or {}).get("login") or ""
        name = repo.get("name") or ""
    head = pr.get("head") or {}
    installation = payload.get("installation") or {}
    return {
        "event": event,
        "action": action,
        "owner": owner,
        "repo": name,
        "full_name": full_name or f"{owner}/{name}",
        "pr_number": pr.get("number"),
        "head_sha": head.get("sha"),
        "installation_id": installation.get("id"),
        "html_url": pr.get("html_url"),
    }


def _extract_admin_token(
    authorization: str | None,
    x_admin_token: str | None,
) -> str | None:
    if x_admin_token:
        return x_admin_token.strip() or None
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def require_admin(
    settings: Settings,
    authorization: str | None = None,
    x_admin_token: str | None = None,
    form_token: str | None = None,
) -> None:
    """Enforce ADMIN_TOKEN. Unset → 503; mismatch → 403."""
    expected = (settings.admin_token or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_TOKEN not configured — set env to enable jobs API",
        )
    provided = form_token or _extract_admin_token(authorization, x_admin_token)
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="forbidden")


async def _get_pool(settings: Settings):
    global _arq_pool
    pool = _arq_pool
    if pool is None:
        pool = await create_arq_pool(settings.redis_url)
        _arq_pool = pool
    return pool


async def _retry_job(settings: Settings, id_or_delivery: str) -> dict[str, Any]:
    record = await resolve_job(settings.database_url, id_or_delivery)
    if not record:
        raise HTTPException(status_code=404, detail="job not found")
    payload = record.get("payload")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="job has no payload archive")

    pool = await _get_pool(settings)
    arq_job_id = await enqueue_process_pr(pool, payload)
    try:
        new_record = await record_job(
            settings.database_url,
            payload=payload,
            status="queued",
            arq_job_id=arq_job_id,
            max_jobs=settings.jobs_list_max,
        )
    except Exception:
        logger.exception("record_job after retry failed")
        new_record = {"id": None, "status": "queued"}

    return {
        "status": "queued",
        "retried_from": record.get("id"),
        "job": {
            "id": new_record.get("id"),
            "delivery_id": payload.get("delivery_id"),
            "owner": payload.get("owner"),
            "repo": payload.get("repo"),
            "pr": payload.get("pr_number"),
            "sha": payload.get("head_sha"),
            "status": "queued",
            "arq_job_id": arq_job_id,
        },
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "pr-sentinel-api"}


@app.get("/metrics")
async def get_metrics(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    """In-process counters (JSON). Same ADMIN_TOKEN pattern as /jobs."""
    settings = get_settings()
    require_admin(settings, authorization=authorization, x_admin_token=x_admin_token)
    return {"counters": metrics_mod.snapshot()}


@app.get("/", response_class=HTMLResponse)
async def install_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "install.html", {})


@app.get("/console", response_class=HTMLResponse)
async def console_page(request: Request) -> HTMLResponse:
    settings = get_settings()
    raw_status = request.query_params.get("status")
    status_filter = raw_status.strip() if isinstance(raw_status, str) and raw_status.strip() else None
    jobs: list[dict[str, Any]] = []
    overview_jobs: list[dict[str, Any]] = []
    try:
        jobs = await list_jobs(settings.database_url, limit=50, status=status_filter)
        # Overview counts from recent unfiltered list so status links stay useful
        if status_filter:
            overview_jobs = await list_jobs(settings.database_url, limit=50)
        else:
            overview_jobs = jobs
    except Exception:
        logger.exception("list_jobs for console failed")
    admin_token = request.cookies.get("pr_sentinel_admin_token") or ""
    flash = None
    if request.query_params.get("ok"):
        flash = {"kind": "ok", "message": request.query_params.get("ok")}
    if request.query_params.get("err"):
        flash = {"kind": "err", "message": request.query_params.get("err")}
    status_counts = aggregate_status_counts(overview_jobs)
    return templates.TemplateResponse(
        request,
        "console.html",
        {
            "jobs": jobs,
            "admin_token": admin_token,
            "flash": flash,
            "status_counts": status_counts,
            "status_filter": status_filter,
        },
    )


@app.post("/console/set-token")
async def console_set_token(admin_token: str = Form(default="")) -> Response:
    resp = RedirectResponse(url="/console", status_code=303)
    if admin_token:
        resp.set_cookie(
            "pr_sentinel_admin_token",
            admin_token,
            httponly=True,
            samesite="lax",
            max_age=86400 * 7,
        )
    else:
        resp.delete_cookie("pr_sentinel_admin_token")
    return resp


@app.post("/console/retry/{job_id}")
async def console_retry(
    job_id: str,
    admin_token: str = Form(default=""),
    redirect_to: str = Form(default=""),
) -> Response:
    settings = get_settings()
    # Allow detail page to bounce back; only internal /console paths
    dest = "/console"
    if redirect_to.startswith("/console"):
        dest = redirect_to.split("?", 1)[0]
    try:
        require_admin(settings, form_token=admin_token or None)
        result = await _retry_job(settings, job_id)
        msg = f"已重试入队 job={result['job'].get('id')} arq={result['job'].get('arq_job_id')}"
        sep = "&" if "?" in dest else "?"
        # If retrying from detail of original job, land on list with flash
        # (new job id differs); still allow detail redirect when same path used.
        return RedirectResponse(url=f"{dest}{sep}ok={msg}", status_code=303)
    except HTTPException as exc:
        sep = "&" if "?" in dest else "?"
        return RedirectResponse(url=f"{dest}{sep}err={exc.detail}", status_code=303)
    except Exception as exc:
        logger.exception("console retry failed")
        sep = "&" if "?" in dest else "?"
        return RedirectResponse(url=f"{dest}{sep}err={exc}", status_code=303)


@app.get("/console/jobs/{job_id}", response_class=HTMLResponse)
async def console_job_detail(request: Request, job_id: str) -> HTMLResponse:
    settings = get_settings()
    job = None
    try:
        record = await get_job(settings.database_url, job_id)
        if record:
            job = job_to_detail_dict(record)
    except Exception:
        logger.exception("get_job for console detail failed")
    admin_token = request.cookies.get("pr_sentinel_admin_token") or ""
    flash = None
    if request.query_params.get("ok"):
        flash = {"kind": "ok", "message": request.query_params.get("ok")}
    if request.query_params.get("err"):
        flash = {"kind": "err", "message": request.query_params.get("err")}
    return templates.TemplateResponse(
        request,
        "job_detail.html",
        {"job": job, "job_id": job_id, "admin_token": admin_token, "flash": flash},
    )


@app.get("/jobs")
async def get_jobs(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    limit: int = 50,
    status: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    require_admin(settings, authorization=authorization, x_admin_token=x_admin_token)
    status_filter = status.strip() if isinstance(status, str) and status.strip() else None
    jobs = await list_jobs(
        settings.database_url,
        limit=min(max(limit, 1), 200),
        status=status_filter,
    )
    return {"jobs": jobs, "count": len(jobs), "status": status_filter}


@app.get("/jobs/{job_id}")
async def get_job_detail(
    job_id: str,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    settings = get_settings()
    require_admin(settings, authorization=authorization, x_admin_token=x_admin_token)
    record = await get_job(settings.database_url, job_id)
    if not record:
        raise HTTPException(status_code=404, detail="job not found")
    return job_to_detail_dict(record)


@app.post("/jobs/{job_id}/retry")
async def post_job_retry(
    job_id: str,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> JSONResponse:
    settings = get_settings()
    require_admin(settings, authorization=authorization, x_admin_token=x_admin_token)
    result = await _retry_job(settings, job_id)
    return JSONResponse(status_code=202, content=result)


@app.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    x_github_delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
) -> Response:
    settings = get_settings()

    # 1) Rate limit (before reading body) — Redis INCR+EXPIRE; fail-open on Redis errors
    client_host = (request.client.host if request.client else None) or "unknown"
    allowed = await check_webhook_rate_limit(
        settings.redis_url,
        client_host,
        limit=settings.webhook_rate_limit,
        window_seconds=settings.webhook_rate_window_seconds,
        prefix=settings.webhook_rate_limit_prefix,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="rate limit exceeded")

    # 2) Body size — Content-Length first (avoid reading oversized body), then actual len
    max_bytes = settings.webhook_max_body_bytes
    cl_raw = request.headers.get("content-length")
    if cl_raw is not None:
        try:
            if int(cl_raw) > max_bytes:
                raise HTTPException(status_code=413, detail="payload too large")
        except ValueError:
            pass  # non-numeric Content-Length → fall through to body check
    body = await request.body()
    if len(body) > max_bytes:
        raise HTTPException(status_code=413, detail="payload too large")

    # 3) HMAC still required when using smee locally unless explicit skip switch
    if not settings.skip_webhook_verify:
        if not verify_signature(settings.github_webhook_secret, body, x_hub_signature_256):
            logger.warning("webhook signature verification failed delivery=%s", x_github_delivery)
            raise HTTPException(status_code=401, detail="invalid signature")
    else:
        logger.warning("webhook signature verification SKIPPED (dev switch)")

    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON") from exc

    event = x_github_event or ""
    job = extract_job_payload(event, payload)
    if job is None:
        logger.info("ignored event=%s action=%s", event, payload.get("action"))
        return JSONResponse(
            status_code=200,
            content={"status": "ignored", "event": event, "action": payload.get("action")},
        )

    if not job.get("pr_number") or not job.get("head_sha"):
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": "missing pr fields"})

    # Persist delivery id (SET NX) before enqueue — idempotent redelivery
    claimed = await claim_delivery(
        settings.redis_url,
        x_github_delivery,
        prefix=settings.delivery_dedup_prefix,
        ttl=settings.delivery_dedup_ttl,
    )
    if not claimed:
        metrics_mod.incr("webhook_duplicate")
        logutil.info(
            logger,
            "duplicate delivery — ack without re-enqueue",
            delivery_id=x_github_delivery,
            sha=(job.get("head_sha") or ""),
        )
        return JSONResponse(
            status_code=200,
            content={"status": "duplicate", "delivery": x_github_delivery},
        )

    job["delivery_id"] = x_github_delivery

    pool = await _get_pool(settings)

    job_id = await enqueue_process_pr(pool, job)

    store_id = None
    try:
        stored = await record_job(
            settings.database_url,
            payload=job,
            status="queued",
            arq_job_id=job_id,
            max_jobs=settings.jobs_list_max,
        )
        store_id = stored.get("id")
    except Exception:
        logger.exception("record_job failed (enqueue already accepted)")

    metrics_mod.incr("webhook_accepted")
    logutil.info(
        logger,
        f"accepted PR {job['full_name']}#{job['pr_number']} arq={job_id}",
        delivery_id=x_github_delivery,
        job_id=store_id,
        sha=job.get("head_sha"),
    )
    return JSONResponse(
        status_code=202,
        content={
            "status": "queued",
            "job": job,
            "arq_job_id": job_id,
            "store_job_id": store_id,
        },
    )


def create_app() -> FastAPI:
    return app


if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    uvicorn.run("main:app", host=s.api_host, port=s.api_port, reload=False)
