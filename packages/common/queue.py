"""Thin Redis list queue (LPUSH / BRPOP)."""

from __future__ import annotations

import json
import logging
from typing import Any

import redis

logger = logging.getLogger(__name__)


class JobQueue:
    def __init__(self, redis_url: str, queue_key: str = "pr-sentinel:jobs"):
        self.queue_key = queue_key
        self._client = redis.from_url(redis_url, decode_responses=True)

    @property
    def client(self) -> redis.Redis:
        return self._client

    def enqueue(self, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False)
        self._client.lpush(self.queue_key, raw)
        logger.info("enqueued job to %s: %s", self.queue_key, payload.get("head_sha"))

    def dequeue(self, timeout: int = 5) -> dict[str, Any] | None:
        result = self._client.brpop(self.queue_key, timeout=timeout)
        if result is None:
            return None
        _key, raw = result
        return json.loads(raw)

    def ping(self) -> bool:
        return bool(self._client.ping())
