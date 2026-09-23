"""Idempotent PR comment upsert by head_sha marker."""

from __future__ import annotations

import logging
from typing import Any

from .client import GitHubClient, marker_for_sha

logger = logging.getLogger(__name__)


def find_marker_comment(
    comments: list[dict[str, Any]], head_sha: str
) -> dict[str, Any] | None:
    needle = marker_for_sha(head_sha)
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
    """Create or update the sentinel comment for this head_sha.

    Marker format: ``<!-- pr-sentinel:{head_sha} -->``
    Same SHA → PATCH existing comment; different/missing → POST new.
    """
    marker = marker_for_sha(head_sha)
    body = f"{marker}\n{report_body}"

    comments = client.list_issue_comments(owner, repo, pr_number)
    existing = find_marker_comment(comments, head_sha)

    if existing is not None:
        comment_id = int(existing["id"])
        logger.info("updating existing comment %s for sha %s", comment_id, head_sha[:12])
        result = client.update_issue_comment(owner, repo, comment_id, body)
        result["_action"] = "update"
        return result

    logger.info("creating new comment for sha %s", head_sha[:12])
    result = client.create_issue_comment(owner, repo, pr_number, body)
    result["_action"] = "create"
    return result
