"""Sticky PR summary comment — idempotent by owner/repo/pr_number marker."""

from __future__ import annotations

import logging
from typing import Any

from .client import GitHubClient

logger = logging.getLogger(__name__)

VALID_STRATEGIES = frozenset({"update", "recreate", "skip_if_exists"})

# GitHub issue comment body soft ceiling (~65k hard); stay under to avoid 422.
STICKY_BODY_MAX = 60_000
STICKY_TRUNCATION_MARK = "<!-- pr-sentinel:truncated -->"
STICKY_TRUNCATION_NOTE = (
    f"\n\n{STICKY_TRUNCATION_MARK}\n\n"
    "> ⚠️ **报告已截断**（sticky 正文超过约 60000 字符，避免 GitHub 评论体过长 422）。"
)


def clamp_sticky_body(
    marker: str,
    report_body: str,
    *,
    limit: int = STICKY_BODY_MAX,
) -> tuple[str, bool]:
    """Build sticky body ``marker + report``; truncate report if over *limit*.

    Returns ``(body, truncated)``. Marker always preserved at the start.
    """
    body = f"{marker}\n{report_body}"
    if len(body) <= limit:
        return body, False
    note = STICKY_TRUNCATION_NOTE
    prefix = f"{marker}\n"
    budget = limit - len(prefix) - len(note)
    if budget < 0:
        # Extreme: keep marker + as much of note as fits.
        clipped = (prefix + note)[:limit]
        return clipped, True
    return prefix + report_body[:budget] + note, True



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
    update_strategy: str = "update",
) -> dict[str, Any]:
    """Create / update / recreate / skip sticky sentinel summary comment.

    Strategies (from ``.pr-sentinel.yml`` ``update_strategy``):
      - ``update`` (default): PATCH existing or POST new
      - ``recreate``: DELETE existing then POST
      - ``skip_if_exists``: if marker present, skip writing
    """
    strategy = (update_strategy or "update").strip().lower()
    if strategy not in VALID_STRATEGIES:
        logger.warning("unknown update_strategy=%r; falling back to update", update_strategy)
        strategy = "update"

    marker = summary_marker(owner, repo, pr_number)
    body, body_truncated = clamp_sticky_body(marker, report_body)
    if body_truncated:
        logger.warning(
            "sticky body truncated for %s/%s#%s (len was %s, limit %s)",
            owner,
            repo,
            pr_number,
            len(marker) + 1 + len(report_body),
            STICKY_BODY_MAX,
        )

    comments = client.list_issue_comments(owner, repo, pr_number)
    existing = find_summary_comment(comments, owner, repo, pr_number)

    if existing is not None:
        comment_id = int(existing["id"])

        if strategy == "skip_if_exists":
            logger.info(
                "skip_if_exists: sticky comment %s already present for %s/%s#%s",
                comment_id,
                owner,
                repo,
                pr_number,
            )
            return {
                "id": comment_id,
                "body": existing.get("body"),
                "_action": "skip",
            }

        if strategy == "recreate":
            logger.info(
                "recreate: deleting sticky comment %s for %s/%s#%s",
                comment_id,
                owner,
                repo,
                pr_number,
            )
            client.delete_issue_comment(owner, repo, comment_id)
            result = client.create_issue_comment(owner, repo, pr_number, body)
            result["_action"] = "recreate"
            return result

        # update
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
