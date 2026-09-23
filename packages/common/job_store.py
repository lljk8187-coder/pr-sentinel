"""Postgres-backed job archive for list / detail / retry (M5/M9; asyncpg, no ORM)."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


def _detail_view(record: dict[str, Any]) -> dict[str, Any]:
    """GET /jobs/{id} shape: list fields + findings / report_md / check_run_id / updated_at."""
    out = _public_view(record)
    findings = record.get("findings")
    if findings is None:
        findings = []
    elif not isinstance(findings, list):
        findings = []
    out["findings"] = findings
    out["report_md"] = record.get("report_md")
    out["check_run_id"] = record.get("check_run_id")
    if record.get("updated_at") is not None:
        out["updated_at"] = record["updated_at"]
    return out


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _row_to_record(row: asyncpg.Record) -> dict[str, Any]:
    data = dict(row)
    # UUID → str for JSON-friendly API
    if data.get("id") is not None:
        data["id"] = str(data["id"])
    data["created_at"] = _iso(data.get("created_at"))
    data["updated_at"] = _iso(data.get("updated_at"))
    payload = data.get("payload")
    if isinstance(payload, str):
        try:
            data["payload"] = json.loads(payload)
        except json.JSONDecodeError:
            pass
    findings = data.get("findings")
    if isinstance(findings, str):
        try:
            data["findings"] = json.loads(findings)
        except json.JSONDecodeError:
            pass
    return data


async def _connect(database_url: str) -> asyncpg.Connection:
    conn = await asyncpg.connect(database_url)
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
        format="text",
    )
    return conn


async def record_job(
    database_url: str,
    *,
    payload: dict[str, Any],
    status: str = "queued",
    job_id: str | None = None,
    arq_job_id: str | None = None,
    error: str | None = None,
    max_jobs: int | None = None,  # kept for call-site compat; PG uses LIMIT on list
) -> dict[str, Any]:
    """Persist job summary + full payload for later list/retry. Returns stored record."""
    del max_jobs  # unused (list_jobs applies LIMIT)
    jid = uuid.UUID(job_id) if job_id else uuid.uuid4()
    delivery_id = payload.get("delivery_id")
    if delivery_id is not None:
        delivery_id = str(delivery_id)
    now = _now()
    owner = payload.get("owner")
    repo = payload.get("repo")
    pr = payload.get("pr_number")
    sha = payload.get("head_sha")

    insert_sql = """
        INSERT INTO jobs (
            id, delivery_id, owner, repo, pr, sha, status, error, arq_job_id,
            payload, findings, created_at, updated_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9,
            $10::jsonb, '[]'::jsonb, $11, $12
        )
        RETURNING *
    """

    conn = await _connect(database_url)
    try:
        try:
            row = await conn.fetchrow(
                insert_sql,
                jid,
                delivery_id,
                owner,
                repo,
                pr,
                sha,
                status,
                error,
                arq_job_id,
                payload,
                now,
                now,
            )
        except asyncpg.UniqueViolationError:
            # Retry / re-record with same delivery_id → keep UNIQUE, null delivery_id
            logger.info(
                "delivery_id=%s already archived; inserting job without delivery_id",
                delivery_id,
            )
            row = await conn.fetchrow(
                insert_sql,
                jid,
                None,
                owner,
                repo,
                pr,
                sha,
                status,
                error,
                arq_job_id,
                payload,
                now,
                now,
            )
        return _row_to_record(row)
    finally:
        await conn.close()


async def get_job(database_url: str, job_id: str) -> dict[str, Any] | None:
    try:
        jid = uuid.UUID(str(job_id))
    except ValueError:
        return None
    conn = await _connect(database_url)
    try:
        row = await conn.fetchrow("SELECT * FROM jobs WHERE id = $1", jid)
        if not row:
            return None
        return _row_to_record(row)
    finally:
        await conn.close()


async def resolve_job(database_url: str, id_or_delivery: str) -> dict[str, Any] | None:
    """Resolve by job id first, then by delivery_id."""
    job = await get_job(database_url, id_or_delivery)
    if job:
        return job
    conn = await _connect(database_url)
    try:
        row = await conn.fetchrow(
            "SELECT * FROM jobs WHERE delivery_id = $1 ORDER BY created_at DESC LIMIT 1",
            str(id_or_delivery),
        )
        if not row:
            return None
        return _row_to_record(row)
    finally:
        await conn.close()


async def list_jobs(database_url: str, *, limit: int = 50) -> list[dict[str, Any]]:
    conn = await _connect(database_url)
    try:
        rows = await conn.fetch(
            """
            SELECT id, delivery_id, owner, repo, pr, sha, status, error,
                   arq_job_id, created_at
            FROM jobs
            ORDER BY created_at DESC
            LIMIT $1
            """,
            max(0, limit),
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(_public_view(_row_to_record(row)))
        return out
    finally:
        await conn.close()


async def update_job_status(
    database_url: str,
    job_id: str,
    status: str,
    *,
    error: str | None = None,
    arq_job_id: str | None = None,
    findings: list[Any] | None = None,
    report_md: str | None = None,
    check_run_id: int | None = None,
) -> bool:
    """Update status/error/arq; optionally SET findings/report_md/check_run_id when not None."""
    try:
        jid = uuid.UUID(str(job_id))
    except ValueError:
        return False

    conn = await _connect(database_url)
    try:
        row = await conn.fetchrow(
            "SELECT id, error, arq_job_id, findings, report_md, check_run_id FROM jobs WHERE id = $1",
            jid,
        )
        if not row:
            return False

        new_error = error
        if error is None and status in ("queued", "running", "success"):
            new_error = None
        elif error is None:
            new_error = row["error"]

        new_arq = arq_job_id if arq_job_id is not None else row["arq_job_id"]
        new_findings = findings if findings is not None else row["findings"]
        new_report = report_md if report_md is not None else row["report_md"]
        new_check = check_run_id if check_run_id is not None else row["check_run_id"]

        if isinstance(new_findings, str):
            try:
                new_findings = json.loads(new_findings)
            except json.JSONDecodeError:
                new_findings = []

        await conn.execute(
            """
            UPDATE jobs
            SET status = $2,
                error = $3,
                arq_job_id = $4,
                findings = $5::jsonb,
                report_md = $6,
                check_run_id = $7,
                updated_at = $8
            WHERE id = $1
            """,
            jid,
            status,
            new_error,
            new_arq,
            new_findings if new_findings is not None else [],
            new_report,
            new_check,
            _now(),
        )
        return True
    finally:
        await conn.close()


async def update_job_result(
    database_url: str,
    job_id: str,
    *,
    status: str,
    error: str | None = None,
    findings: list[Any] | None = None,
    report_md: str | None = None,
    check_run_id: int | None = None,
    arq_job_id: str | None = None,
) -> bool:
    """Convenience wrapper: write success/failure result fields into jobs."""
    return await update_job_status(
        database_url,
        job_id,
        status,
        error=error,
        arq_job_id=arq_job_id,
        findings=findings,
        report_md=report_md,
        check_run_id=check_run_id,
    )


async def update_job_status_by_payload(
    database_url: str,
    payload: dict[str, Any],
    status: str,
    *,
    error: str | None = None,
    arq_job_id: str | None = None,
    findings: list[Any] | None = None,
    report_md: str | None = None,
    check_run_id: int | None = None,
) -> bool:
    """Best-effort status update using delivery_id or matching owner/repo/pr/sha."""
    kwargs = dict(
        error=error,
        arq_job_id=arq_job_id,
        findings=findings,
        report_md=report_md,
        check_run_id=check_run_id,
    )
    delivery_id = payload.get("delivery_id")
    if delivery_id:
        job = await resolve_job(database_url, str(delivery_id))
        if job and job.get("id"):
            return await update_job_status(
                database_url,
                job["id"],
                status,
                **kwargs,
            )

    conn = await _connect(database_url)
    try:
        row = await conn.fetchrow(
            """
            SELECT id FROM jobs
            WHERE owner = $1 AND repo = $2 AND pr = $3 AND sha = $4
            ORDER BY created_at DESC
            LIMIT 1
            """,
            payload.get("owner"),
            payload.get("repo"),
            payload.get("pr_number"),
            payload.get("head_sha"),
        )
        if not row:
            return False
        return await update_job_status(
            database_url,
            str(row["id"]),
            status,
            **kwargs,
        )
    finally:
        await conn.close()
