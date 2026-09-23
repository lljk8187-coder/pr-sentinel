"""Redis-backed job archive for list / retry (M4 console)."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis_async

logger = logging.getLogger(__name__)

DEFAULT_LIST_KEY = "pr-sentinel:jobs"
DEFAULT_JOB_PREFIX = "pr-sentinel:job:"
DEFAULT_BY_DELIVERY_PREFIX = "pr-sentinel:job:by-delivery:"
DEFAULT_MAX_JOBS = 100


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_key(job_id: str, prefix: str = DEFAULT_JOB_PREFIX) -> str:
    return f"{prefix}{job_id}"


def _delivery_key(delivery_id: str, prefix: str = DEFAULT_BY_DELIVERY_PREFIX) -> str:
    return f"{prefix}{delivery_id}"


def _public_view(record: dict[str, Any]) -> dict[str, Any]:
    """API/list shape: id, delivery_id, owner/repo, pr, sha, status, created_at, error?"""
    out: dict[str, Any] = {
        "id": record.get("id"),
        "delivery_id": record.get("delivery_id"),
        "owner": record.get("owner"),
        "repo": record.get("repo"),
        "pr": record.get("pr"),
        "sha": record.get("sha"),
        "status": record.get("status"),
        "created_at": record.get("created_at"),
    }
    if record.get("error"):
        out["error"] = record["error"]
    if record.get("arq_job_id"):
        out["arq_job_id"] = record["arq_job_id"]
    return out


async def _client(redis_url: str):
    return redis_async.from_url(redis_url, decode_responses=True)


async def record_job(
    redis_url: str,
    *,
    payload: dict[str, Any],
    status: str = "queued",
    job_id: str | None = None,
    arq_job_id: str | None = None,
    error: str | None = None,
    list_key: str = DEFAULT_LIST_KEY,
    job_prefix: str = DEFAULT_JOB_PREFIX,
    by_delivery_prefix: str = DEFAULT_BY_DELIVERY_PREFIX,
    max_jobs: int = DEFAULT_MAX_JOBS,
) -> dict[str, Any]:
    """Persist job summary + full payload for later list/retry. Returns stored record."""
    jid = job_id or str(uuid.uuid4())
    delivery_id = payload.get("delivery_id")
    record: dict[str, Any] = {
        "id": jid,
        "delivery_id": delivery_id,
        "owner": payload.get("owner"),
        "repo": payload.get("repo"),
        "pr": payload.get("pr_number"),
        "sha": payload.get("head_sha"),
        "status": status,
        "created_at": _now_iso(),
        "error": error,
        "arq_job_id": arq_job_id,
        "payload": payload,
    }
    client = await _client(redis_url)
    try:
        await client.set(_job_key(jid, job_prefix), json.dumps(record, ensure_ascii=False))
        await client.lpush(list_key, jid)
        await client.ltrim(list_key, 0, max(0, max_jobs - 1))
        if delivery_id:
            await client.set(_delivery_key(str(delivery_id), by_delivery_prefix), jid)
        return record
    finally:
        await client.aclose()


async def get_job(
    redis_url: str,
    job_id: str,
    *,
    job_prefix: str = DEFAULT_JOB_PREFIX,
) -> dict[str, Any] | None:
    client = await _client(redis_url)
    try:
        raw = await client.get(_job_key(job_id, job_prefix))
        if not raw:
            return None
        return json.loads(raw)
    finally:
        await client.aclose()


async def resolve_job(
    redis_url: str,
    id_or_delivery: str,
    *,
    job_prefix: str = DEFAULT_JOB_PREFIX,
    by_delivery_prefix: str = DEFAULT_BY_DELIVERY_PREFIX,
) -> dict[str, Any] | None:
    """Resolve by job id first, then by delivery_id."""
    job = await get_job(redis_url, id_or_delivery, job_prefix=job_prefix)
    if job:
        return job
    client = await _client(redis_url)
    try:
        mapped = await client.get(_delivery_key(id_or_delivery, by_delivery_prefix))
        if not mapped:
            return None
        raw = await client.get(_job_key(mapped, job_prefix))
        if not raw:
            return None
        return json.loads(raw)
    finally:
        await client.aclose()


async def list_jobs(
    redis_url: str,
    *,
    limit: int = 50,
    list_key: str = DEFAULT_LIST_KEY,
    job_prefix: str = DEFAULT_JOB_PREFIX,
) -> list[dict[str, Any]]:
    client = await _client(redis_url)
    try:
        ids = await client.lrange(list_key, 0, max(0, limit - 1))
        out: list[dict[str, Any]] = []
        for jid in ids:
            raw = await client.get(_job_key(jid, job_prefix))
            if not raw:
                continue
            try:
                out.append(_public_view(json.loads(raw)))
            except json.JSONDecodeError:
                logger.warning("corrupt job record id=%s", jid)
        return out
    finally:
        await client.aclose()


async def update_job_status(
    redis_url: str,
    job_id: str,
    status: str,
    *,
    error: str | None = None,
    job_prefix: str = DEFAULT_JOB_PREFIX,
) -> bool:
    client = await _client(redis_url)
    try:
        key = _job_key(job_id, job_prefix)
        raw = await client.get(key)
        if not raw:
            # Also try matching by payload delivery / arq id inside list — caller should pass store id
            return False
        record = json.loads(raw)
        record["status"] = status
        if error is not None:
            record["error"] = error
        elif status in ("queued", "running", "success"):
            record["error"] = None
        record["updated_at"] = _now_iso()
        await client.set(key, json.dumps(record, ensure_ascii=False))
        return True
    finally:
        await client.aclose()


async def update_job_status_by_payload(
    redis_url: str,
    payload: dict[str, Any],
    status: str,
    *,
    error: str | None = None,
    list_key: str = DEFAULT_LIST_KEY,
    job_prefix: str = DEFAULT_JOB_PREFIX,
    by_delivery_prefix: str = DEFAULT_BY_DELIVERY_PREFIX,
) -> bool:
    """Best-effort status update using delivery_id or scanning recent jobs for matching sha/pr."""
    delivery_id = payload.get("delivery_id")
    if delivery_id:
        job = await resolve_job(
            redis_url,
            str(delivery_id),
            job_prefix=job_prefix,
            by_delivery_prefix=by_delivery_prefix,
        )
        if job and job.get("id"):
            return await update_job_status(
                redis_url, job["id"], status, error=error, job_prefix=job_prefix
            )

    # Fallback: match newest list entry with same owner/repo/pr/sha
    client = await _client(redis_url)
    try:
        ids = await client.lrange(list_key, 0, 49)
        for jid in ids:
            raw = await client.get(_job_key(jid, job_prefix))
            if not raw:
                continue
            record = json.loads(raw)
            if (
                record.get("owner") == payload.get("owner")
                and record.get("repo") == payload.get("repo")
                and record.get("pr") == payload.get("pr_number")
                and record.get("sha") == payload.get("head_sha")
            ):
                return await update_job_status(
                    redis_url, jid, status, error=error, job_prefix=job_prefix
                )
        return False
    finally:
        await client.aclose()
