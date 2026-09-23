"""FastAPI webhook receiver for GitHub pull_request events (arq enqueue)."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

_ROOT = Path(__file__).resolve().parents[2]
for p in (_ROOT, _ROOT / "packages", _ROOT / "packages" / "github"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from common.queue import claim_delivery, create_arq_pool, enqueue_process_pr  # noqa: E402
from common.settings import Settings, get_settings  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pr-sentinel.api")

TARGET_ACTIONS = {"opened", "synchronize"}

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
    version="0.2.0",
    description="M2 quality-gate webhook API",
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "pr-sentinel-api"}


@app.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    x_github_delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
) -> Response:
    settings = get_settings()
    body = await request.body()

    # HMAC still required when using smee locally unless explicit skip switch
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
        logger.info("duplicate delivery=%s — ack without re-enqueue", x_github_delivery)
        return JSONResponse(
            status_code=200,
            content={"status": "duplicate", "delivery": x_github_delivery},
        )

    job["delivery_id"] = x_github_delivery

    pool = _arq_pool
    if pool is None:
        pool = await create_arq_pool(settings.redis_url)

    job_id = await enqueue_process_pr(pool, job)
    logger.info(
        "accepted PR %s#%s sha=%s delivery=%s arq=%s",
        job["full_name"],
        job["pr_number"],
        (job.get("head_sha") or "")[:12],
        x_github_delivery,
        job_id,
    )
    return JSONResponse(
        status_code=202,
        content={"status": "queued", "job": job, "arq_job_id": job_id},
    )


def create_app() -> FastAPI:
    return app


if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    uvicorn.run("main:app", host=s.api_host, port=s.api_port, reload=False)
