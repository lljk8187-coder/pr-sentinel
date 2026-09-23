"""FastAPI webhook receiver for GitHub pull_request events."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

# Allow running without install: repo root + packages on path
_ROOT = Path(__file__).resolve().parents[2]
for p in (_ROOT, _ROOT / "packages", _ROOT / "packages" / "github"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from common.queue import JobQueue  # noqa: E402
from common.settings import Settings, get_settings  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pr-sentinel.api")

app = FastAPI(title="pr-sentinel", version="0.1.0", description="M1 quality-gate webhook API")

TARGET_ACTIONS = {"opened", "synchronize"}


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Verify X-Hub-Signature-256 (sha256=<hex>)."""
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


def get_queue(settings: Settings | None = None) -> JobQueue:
    s = settings or get_settings()
    return JobQueue(s.redis_url, s.queue_key)


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

    queue = get_queue(settings)
    queue.enqueue(job)
    logger.info(
        "accepted PR %s#%s sha=%s delivery=%s",
        job["full_name"],
        job["pr_number"],
        (job.get("head_sha") or "")[:12],
        x_github_delivery,
    )
    return JSONResponse(status_code=202, content={"status": "queued", "job": job})


def create_app() -> FastAPI:
    return app


if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    uvicorn.run("main:app", host=s.api_host, port=s.api_port, reload=False)
