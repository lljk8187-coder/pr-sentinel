"""Tiny structured-ish log helpers (fields baked into message for grep)."""

from __future__ import annotations

import logging
from typing import Any


def fmt_ctx(
    *,
    delivery_id: Any = None,
    job_id: Any = None,
    sha: Any = None,
) -> str:
    parts: list[str] = []
    if delivery_id is not None and delivery_id != "":
        parts.append(f"delivery_id={delivery_id}")
    if job_id is not None and job_id != "":
        parts.append(f"job_id={job_id}")
    if sha is not None and sha != "":
        parts.append(f"sha={str(sha)[:12]}")
    return " ".join(parts)


def info(
    logger: logging.Logger,
    msg: str,
    *,
    delivery_id: Any = None,
    job_id: Any = None,
    sha: Any = None,
    **extra_fields: Any,
) -> None:
    ctx = fmt_ctx(delivery_id=delivery_id, job_id=job_id, sha=sha)
    full = f"{msg} {ctx}".strip() if ctx else msg
    extra = {
        "delivery_id": delivery_id,
        "job_id": job_id,
        "sha": (str(sha)[:12] if sha else None),
        **extra_fields,
    }
    logger.info(full, extra={k: v for k, v in extra.items() if v is not None})


def warning(
    logger: logging.Logger,
    msg: str,
    *,
    delivery_id: Any = None,
    job_id: Any = None,
    sha: Any = None,
    **extra_fields: Any,
) -> None:
    ctx = fmt_ctx(delivery_id=delivery_id, job_id=job_id, sha=sha)
    full = f"{msg} {ctx}".strip() if ctx else msg
    extra = {
        "delivery_id": delivery_id,
        "job_id": job_id,
        "sha": (str(sha)[:12] if sha else None),
        **extra_fields,
    }
    logger.warning(full, extra={k: v for k, v in extra.items() if v is not None})
