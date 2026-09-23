"""Sticky PR summary comment — idempotent by owner/repo/pr_number marker."""

from __future__ import annotations

import logging
from typing import Any

from .client import GitHubClient

logger = logging.getLogger(__name__)


def summary_marker(owner: str, repo: str, pr_number: int) -> str:
    """Sticky marker: ``<!-- pr-sentinel:summary:{owner}/{repo}:{pr_number} -->``."""
    return f"<!-- pr-sentinel:summary:{owner}/{repo}:{pr_number} -->"


def find_summary_comment(
    comments: list[dict[str, Any]], owner: str, repo: str, pr_number: int
) -> dict[str, Any] | None:
    needle = summary_marker(owner, repo, pr_number)
    for c in comments:
        body = c.get("body") or ""
        if needle in body:
            return c
    return None


def upsert_pr_comment(
    client: GitHubClient,
    *,
    owner: str,
    repo: str,
    pr_number: int,
    head_sha: str,
    report_body: str,
) -> dict[str, Any]:
    """Create or update the sticky sentinel summary comment for this PR.

    Marker is stable per PR (not per head_sha). Same PR → PATCH; else POST.
    ``head_sha`` is included in the report body only (for display).
    """
    marker = summary_marker(owner, repo, pr_number)
    body = f"{marker}\n{report_body}"

    comments = client.list_issue_comments(owner, repo, pr_number)
    existing = find_summary_comment(comments, owner, repo, pr_number)

    if existing is not None:
        comment_id = int(existing["id"])
        logger.info(
            "updating sticky summary comment %s for %s/%s#%s (sha=%s)",
            comment_id,
            owner,
            repo,
            pr_number,
            head_sha[:12],
        )
        result = client.update_issue_comment(owner, repo, comment_id, body)
        result["_action"] = "update"
        return result

    logger.info("creating sticky summary comment for %s/%s#%s", owner, repo, pr_number)
    result = client.create_issue_comment(owner, repo, pr_number, body)
    result["_action"] = "create"
    return result
