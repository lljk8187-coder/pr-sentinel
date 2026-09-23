"""Queue consumer: fetch PR files → fake analyze → idempotent comment."""

from __future__ import annotations

import logging
import signal
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
for p in (_ROOT, _ROOT / "packages", _ROOT / "packages" / "github"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from common.queue import JobQueue  # noqa: E402
from common.settings import Settings, get_settings  # noqa: E402
from pr_sentinel_github.analyzer import FakeAnalyzer  # noqa: E402
from pr_sentinel_github.client import GitHubClient  # noqa: E402
from pr_sentinel_github.comments import upsert_pr_comment  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("pr-sentinel.worker")

_running = True


def _handle_signal(signum: int, _frame: Any) -> None:
    global _running
    logger.info("received signal %s, shutting down…", signum)
    _running = False


def build_client(settings: Settings, installation_id: int | None = None) -> GitHubClient:
    private_key = settings.github_app_private_key
    if not private_key and settings.github_app_private_key_path:
        private_key = Path(settings.github_app_private_key_path).read_text(encoding="utf-8")

    use_fixtures = settings.use_fixtures
    if not settings.github_token and not (settings.github_app_id and private_key):
        use_fixtures = True

    return GitHubClient(
        token=settings.github_token,
        app_id=settings.github_app_id,
        app_private_key=private_key,
        installation_id=installation_id,
        use_fixtures=use_fixtures,
        fixtures_dir=settings.fixtures_path(),
    )


def process_job(job: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    owner = job["owner"]
    repo = job["repo"]
    pr_number = int(job["pr_number"])
    head_sha = job["head_sha"]
    installation_id = job.get("installation_id")

    client = build_client(settings, installation_id=installation_id)
    try:
        files = client.list_pr_files(owner, repo, pr_number)
        report = FakeAnalyzer().analyze(files, head_sha=head_sha, pr_number=pr_number)
        result = upsert_pr_comment(
            client,
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            head_sha=head_sha,
            report_body=report,
        )
        logger.info(
            "done %s/%s#%s action=%s",
            owner,
            repo,
            pr_number,
            result.get("_action"),
        )
        return result
    finally:
        client.close()


def run_forever(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    queue = JobQueue(settings.redis_url, settings.queue_key)
    logger.info("worker started redis=%s key=%s", settings.redis_url, settings.queue_key)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    while _running:
        try:
            job = queue.dequeue(timeout=5)
        except Exception:
            logger.exception("dequeue failed; sleeping")
            time.sleep(2)
            continue
        if job is None:
            continue
        try:
            process_job(job, settings)
        except Exception:
            logger.exception("job failed: %s", job)


if __name__ == "__main__":
    run_forever()
