"""arq worker: load config → fetch PR files → rules(+llm) analyze → sticky comment."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
for p in (_ROOT, _ROOT / "packages", _ROOT / "packages" / "github"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

import httpx  # noqa: E402
from arq import Retry  # noqa: E402

from common.config import CONFIG_FILENAME, load_repo_config  # noqa: E402
from common.job_store import update_job_status_by_payload  # noqa: E402
from common import logutil  # noqa: E402
from common import metrics as metrics_mod  # noqa: E402
from common.queue import redis_settings_from_url  # noqa: E402
from common.settings import Settings, get_settings  # noqa: E402
from pr_sentinel_github.analyzer import get_analyzer  # noqa: E402
from pr_sentinel_github.client import GitHubClient  # noqa: E402
from pr_sentinel_github.check_runs import (  # noqa: E402
    publish_check_run,
    publish_inline_comments,
)
from pr_sentinel_github.comments import upsert_pr_comment  # noqa: E402
from pr_sentinel_github.llm import (  # noqa: E402
    LLMTransientError,
    redact_findings_for_storage,
)
from pr_sentinel_github.rules.base import Finding  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("pr-sentinel.worker")

# Business / non-retryable outcomes (caller may return these without raising).
SKIP_ACTIONS = frozenset({"skipped_comment", "skip", "skipped"})


class BusinessSkip(Exception):
    """Intentional skip — do not consume arq retries."""

    def __init__(self, reason: str, payload: dict[str, Any] | None = None):
        super().__init__(reason)
        self.reason = reason
        self.payload = payload or {"_action": "skipped", "reason": reason}


def _findings_from_redacted_dicts(items: list[dict[str, Any]]) -> list[Finding]:
    """Rebuild Finding objects from redact_findings_for_storage dicts for publish_*."""
    out: list[Finding] = []
    for d in items:
        if not isinstance(d, dict):
            continue
        meta = d.get("meta")
        out.append(
            Finding(
                rule_id=str(d.get("rule_id") or "finding"),
                severity=str(d.get("severity") or "info"),
                message=str(d.get("message") or ""),
                filename=d.get("filename") or d.get("path"),
                meta=dict(meta) if isinstance(meta, dict) else {},
                source=str(d.get("source") or "rules"),
                detail=str(d.get("detail") or ""),
                line=d.get("line"),
            )
        )
    return out


def build_client(settings: Settings, installation_id: int | None = None) -> GitHubClient:
    private_key = settings.github_app_private_key
    if not private_key and settings.github_app_private_key_path:
        private_key = Path(settings.github_app_private_key_path).read_text(encoding="utf-8")

    use_fixtures = settings.use_fixtures
    # If neither App nor PAT configured, force fixtures
    if not settings.github_token and not (settings.github_app_id and private_key):
        use_fixtures = True

    return GitHubClient(
        token=settings.github_token,
        app_id=settings.github_app_id,
        app_private_key=private_key,
        installation_id=installation_id,
        use_fixtures=use_fixtures,
        fixtures_dir=settings.fixtures_path(),
        max_pages=settings.diff_max_pages,
        per_page=settings.diff_per_page,
        max_files=settings.diff_max_files,
    )


def _load_job_config(
    client: GitHubClient,
    settings: Settings,
    owner: str,
    repo: str,
) -> tuple[dict[str, Any], list[str]]:
    """Load DEFAULT_CONFIG ⊕ default-branch `.pr-sentinel.yml` (never PR branch)."""
    if client._should_use_fixtures:  # noqa: SLF001 — intentional fixture branch
        return load_repo_config(
            use_fixtures=True,
            fixtures_dir=settings.fixtures_path(),
        )

    def fetch_yml() -> str | None:
        default_branch = client.get_default_branch(owner, repo)
        return client.get_file_contents(
            owner, repo, CONFIG_FILENAME, ref=default_branch
        )

    return load_repo_config(fetch_yml=fetch_yml)


def _is_transient_http(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code >= 500 or code == 429
    if isinstance(exc, LLMTransientError):
        return True
    return False


def process_job(job: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    """Synchronous job body (also callable from tests). Re-entrant sticky upsert."""
    settings = settings or get_settings()

    owner = job["owner"]
    repo = job["repo"]
    pr_number = int(job["pr_number"])
    head_sha = job["head_sha"]
    installation_id = job.get("installation_id")

    client = build_client(settings, installation_id=installation_id)
    try:
        config, config_notes = _load_job_config(client, settings, owner, repo)

        # Env truncation overlays (ops knobs) onto merged config
        config.setdefault("diff", {})
        config["diff"]["max_pages"] = settings.diff_max_pages
        config["diff"]["per_page"] = settings.diff_per_page
        config["diff"]["max_files"] = settings.diff_max_files
        client.max_pages = settings.diff_max_pages
        client.per_page = settings.diff_per_page
        client.max_files = settings.diff_max_files

        files = client.list_pr_files(owner, repo, pr_number)
        analyzer = get_analyzer(config)
        analysis = analyzer.analyze(
            files,
            head_sha=head_sha,
            pr_number=pr_number,
            truncated=client.truncated,
            config=config,
            config_notes=config_notes,
        )
        report = analysis.markdown
        findings = analysis.findings

        # M14: redact before Check Run / sticky / inline publish AND storage.
        # Same redacted findings+report feed outbound GitHub + Postgres writeback.
        redacted_findings, redacted_report = redact_findings_for_storage(
            [f.to_dict() for f in findings],
            report,
            config,
        )
        findings = _findings_from_redacted_dicts(redacted_findings)
        report = redacted_report if redacted_report is not None else report

        out: dict[str, Any] = {
            "_action": "analyzed",
            "report": report,
            "findings": redacted_findings,
        }

        if config.get("check_run", True):
            out["check_run"] = publish_check_run(
                client,
                owner=owner,
                repo=repo,
                head_sha=head_sha,
                findings=findings,
                report_body=report,
            )

        if config.get("summary_comment", True):
            strategy = str(config.get("update_strategy") or "update")
            sticky = upsert_pr_comment(
                client,
                owner=owner,
                repo=repo,
                pr_number=pr_number,
                head_sha=head_sha,
                report_body=report,
                update_strategy=strategy,
            )
            out.update(sticky)
            logger.info(
                "done %s/%s#%s action=%s truncated=%s strategy=%s",
                owner,
                repo,
                pr_number,
                sticky.get("_action"),
                client.truncated,
                strategy,
            )
        else:
            logger.info("summary_comment=false — skipping sticky comment")
            out["_action"] = "skipped_comment"

        if config.get("inline_comments", True):
            out["inline_comments"] = publish_inline_comments(
                client,
                owner=owner,
                repo=repo,
                pr_number=pr_number,
                head_sha=head_sha,
                findings=findings,
                files=files,
            )

        return out
    finally:
        client.close()


async def process_pr(ctx: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    """arq function name must match enqueue_job('process_pr', …).

    Transient network/5xx/429/timeout → ``Retry`` with backoff while
    ``job_try < max_tries``; on the last try write ``failed``
    (``transient exhausted:…``) and return normally so PG is not stuck
    at ``running``. Non-transient errors fail immediately (no Retry).
    Business skips return normally (no infinite retry).
    """
    settings = ctx.get("settings") or get_settings()
    job_try = int(ctx.get("job_try") or 1)
    delivery_id = job.get("delivery_id")
    sha = job.get("head_sha")
    store_job_id = job.get("store_job_id") or job.get("id")

    async def _status(
        status: str,
        error: str | None = None,
        *,
        findings=None,
        report_md=None,
        check_run_id=None,
    ) -> None:
        try:
            await update_job_status_by_payload(
                settings.database_url,
                job,
                status,
                error=error,
                findings=findings,
                report_md=report_md,
                check_run_id=check_run_id,
            )
        except Exception:
            logger.exception("job status update failed status=%s", status)

    logutil.info(
        logger,
        "process_pr status=running",
        delivery_id=delivery_id,
        job_id=store_job_id,
        sha=sha,
    )
    await _status("running")
    try:
        result = process_job(job, settings)
        check_run = result.get("check_run") or {}
        check_run_id = check_run.get("id") if isinstance(check_run, dict) else None
        await _status(
            "success",
            findings=result.get("findings"),
            report_md=result.get("report"),
            check_run_id=check_run_id,
        )
        metrics_mod.incr("worker_success")
        logutil.info(
            logger,
            "process_pr status=success",
            delivery_id=delivery_id,
            job_id=store_job_id,
            sha=sha,
        )
        return result
    except BusinessSkip as exc:
        logutil.info(
            logger,
            f"process_pr business skip: {exc.reason}",
            delivery_id=delivery_id,
            job_id=store_job_id,
            sha=sha,
        )
        await _status("success", error=f"skipped:{exc.reason}")
        metrics_mod.incr("worker_success")
        return exc.payload
    except Exception as exc:
        if _is_transient_http(exc):
            max_tries = int(getattr(WorkerSettings, "max_tries", 3) or 3)
            # Exponential-ish backoff: 5, 10, 20… capped at 60s
            defer = min(60, 5 * (2 ** max(0, job_try - 1)))
            logutil.warning(
                logger,
                f"transient error try={job_try} defer={defer}s: {exc}",
                delivery_id=delivery_id,
                job_id=store_job_id,
                sha=sha,
            )
            if job_try >= max_tries:
                # Last try: mark failed and return normally so PG is not stuck
                # at running. Do NOT raise Retry (arq would re-enqueue then
                # reject at job_try > max_tries without calling us again).
                err = f"transient exhausted: {exc}"[:500]
                await _status("failed", error=err)
                metrics_mod.incr("worker_fail")
                logutil.warning(
                    logger,
                    "process_pr status=failed",
                    delivery_id=delivery_id,
                    job_id=store_job_id,
                    sha=sha,
                )
                return {"_action": "failed", "error": err}
            # Middle tries: surface retry hint, then arq Retry (no enqueue_job).
            await _status("running", error=f"retrying try={job_try}")
            raise Retry(defer=defer) from exc
        # Non-transient (e.g. 4xx GitHub, programming errors): fail the job
        # without Retry so arq won't keep spinning on clear business failures.
        logger.exception("non-retryable error in process_pr: %s", exc)
        await _status("failed", error=str(exc)[:500])
        metrics_mod.incr("worker_fail")
        logutil.warning(
            logger,
            "process_pr status=failed",
            delivery_id=delivery_id,
            job_id=store_job_id,
            sha=sha,
        )
        raise


async def on_startup(ctx: dict[str, Any]) -> None:
    ctx["settings"] = get_settings()
    logger.info("arq worker startup redis=%s db=%s", ctx["settings"].redis_url, ctx["settings"].database_url)


class WorkerSettings:
    """arq CLI entry: ``arq apps.worker.main.WorkerSettings`` (with PYTHONPATH)."""

    functions = [process_pr]
    on_startup = on_startup
    redis_settings = redis_settings_from_url(get_settings().redis_url)
    # M3: failure retries with timeout
    max_tries = 3
    job_timeout = 300  # seconds
    retry_jobs = True


if __name__ == "__main__":
    # ``python apps/worker/main.py`` → run arq worker
    import os

    os.chdir(_ROOT)
    from arq.worker import run_worker

    run_worker(WorkerSettings)
