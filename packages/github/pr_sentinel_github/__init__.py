"""GitHub API client for pr-sentinel (App placeholder / PAT / fixtures)."""

from .client import GitHubClient
from .analyzer import FakeAnalyzer, build_report
from .comments import upsert_pr_comment, summary_marker

__all__ = [
    "GitHubClient",
    "FakeAnalyzer",
    "build_report",
    "upsert_pr_comment",
    "summary_marker",
]
