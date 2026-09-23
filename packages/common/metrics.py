"""Lightweight in-process counters (no prometheus). Process-local only."""

from __future__ import annotations

from typing import Any

_COUNTERS: dict[str, int] = {
    "webhook_accepted": 0,
    "webhook_duplicate": 0,
    "worker_success": 0,
    "worker_fail": 0,
}


def incr(name: str, amount: int = 1) -> None:
    if name not in _COUNTERS:
        _COUNTERS[name] = 0
    _COUNTERS[name] += amount


def snapshot() -> dict[str, Any]:
    return dict(_COUNTERS)


def reset_for_tests() -> None:
    for k in list(_COUNTERS):
        _COUNTERS[k] = 0
