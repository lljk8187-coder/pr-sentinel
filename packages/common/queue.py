"""Redis + arq job queue and X-GitHub-Delivery dedup (SET NX)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import redis.asyncio as redis_async
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

logger = logging.getLogger(__name__)


def redis_settings_from_url(redis_url: str) -> RedisSettings:
    """Parse REDIS_URL into arq RedisSettings."""
    u = urlparse(redis_url)
    db = 0
    if u.path and u.path.strip("/"):
        try:
            db = int(u.path.strip("/").split("/")[0])
        except ValueError:
            db = 0
    return RedisSettings(
        host=u.hostname or "localhost",
        port=u.port or 6379,
        database=db,
        password=u.password,
        username=u.username,
    )


async def create_arq_pool(redis_url: str) -> ArqRedis:
    return await create_pool(redis_settings_from_url(redis_url))


async def claim_delivery(
    redis_url: str,
    delivery_id: str | None,
    *,
    prefix: str = "pr-sentinel:delivery:",
    ttl: int = 86400 * 7,
) -> bool:
    """Persist X-GitHub-Delivery with SET NX. Return True if newly claimed.

    Missing delivery_id is treated as always-new (claim succeeds) so local
    curls without the header still work; production GitHub always sends it.
    """
    if not delivery_id:
        logger.warning("no X-GitHub-Delivery; skipping dedup claim")
        return True

    client = redis_async.from_url(redis_url, decode_responses=True)
    try:
        key = f"{prefix}{delivery_id}"
        ok = await client.set(key, "1", nx=True, ex=ttl)
        return bool(ok)
    finally:
        await client.aclose()


async def check_webhook_rate_limit(
    redis_url: str,
    client_key: str,
    *,
    limit: int = 120,
    window_seconds: int = 60,
    prefix: str = "pr-sentinel:webhook:rl:",
) -> bool:
    """INCR+EXPIRE fixed-window rate limit. Return True if allowed; False if over limit.

    Fail-open on Redis errors: log a warning and allow the request through so a
    Redis blip cannot take down GitHub webhook delivery (availability over
    strict enforcement when the limiter itself is unavailable).
    """
    client = None
    try:
        client = redis_async.from_url(redis_url, decode_responses=True)
        key = f"{prefix}{client_key}"
        n = await client.incr(key)
        if n == 1:
            await client.expire(key, window_seconds)
        return n <= limit
    except Exception:
        logger.warning(
            "webhook rate limit check failed (fail-open); allowing request",
            exc_info=True,
        )
        return True
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass


async def enqueue_process_pr(pool: ArqRedis, job: dict[str, Any]) -> str | None:
    """Enqueue the arq function ``process_pr``. Returns arq job id."""
    job_result = await pool.enqueue_job("process_pr", job)
    if job_result is None:
        # arq returns None when a job with the same _job_id already exists
        logger.warning("arq enqueue returned None (duplicate job id?)")
        return None
    return job_result.job_id
