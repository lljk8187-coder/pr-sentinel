"""arq worker: fetch PR files → fake analyze → sticky summary comment."""

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

from common.defaults import get_default_config  # noqa: E402
from common.queue import redis_settings_from_url  # noqa: E402
from common.settings import Settings, get_settings  # noqa: E402
from pr_sentinel_github.analyzer import FakeAnalyzer  # noqa: E402
from pr_sentinel_github.client import GitHubClient  # noqa: E402
from pr_sentinel_github.comments import upsert_pr_comment  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("pr-sentinel.worker")


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


def process_job(job: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    """Synchronous job body (also callable from tests)."""
    settings = settings or get_settings()
    config = get_default_config()  # M1: built-in defaults, no repo .pr-sentinel.yml read

    owner = job["owner"]
    repo = job["repo"]
    pr_number = int(job["pr_number"])
    head_sha = job["head_sha"]
    installation_id = job.get("installation_id")

    # Overlay env truncation onto config for report display
    config["diff"]["max_pages"] = settings.diff_max_pages
    config["diff"]["max_files"] = settings.diff_max_files

    client = build_client(settings, installation_id=installation_id)
    try:
        files = client.list_pr_files(owner, repo, pr_number)
        report = FakeAnalyzer().analyze(
            files,
            head_sha=head_sha,
            pr_number=pr_number,
            truncated=client.truncated,
            config=config,
        )
        result = upsert_pr_comment(
            client,
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            head_sha=head_sha,
            report_body=report,
        )
        logger.info(
            "done %s/%s#%s action=%s truncated=%s",
            owner,
            repo,
            pr_number,
            result.get("_action"),
            client.truncated,
        )
        return result
    finally:
        client.close()


async def process_pr(ctx: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    """arq function name must match enqueue_job('process_pr', …)."""
    settings = ctx.get("settings") or get_settings()
    return process_job(job, settings)


async def on_startup(ctx: dict[str, Any]) -> None:
    ctx["settings"] = get_settings()
    logger.info("arq worker startup redis=%s", ctx["settings"].redis_url)


class WorkerSettings:
    """arq CLI entry: ``arq apps.worker.main.WorkerSettings`` (with PYTHONPATH)."""

    functions = [process_pr]
    on_startup = on_startup
    redis_settings = redis_settings_from_url(get_settings().redis_url)


if __name__ == "__main__":
    # ``python apps/worker/main.py`` → run arq worker
    import os

    os.chdir(_ROOT)
    from arq.worker import run_worker

    run_worker(WorkerSettings)
