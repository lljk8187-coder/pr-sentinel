"""Sticky comment update_strategy behaviour."""

from __future__ import annotations

from pathlib import Path

from pr_sentinel_github.client import GitHubClient
from pr_sentinel_github.comments import summary_marker, upsert_pr_comment

SHA = "deadbeefcafebabe000011112222333344445555"


def _client_with_marker(fixtures_dir: Path, tmp_path: Path) -> GitHubClient:
    (tmp_path / "pr_files.json").write_text((fixtures_dir / "pr_files.json").read_text())
    (tmp_path / "issue_comments.json").write_text(
        (fixtures_dir / "issue_comments_with_marker.json").read_text()
    )
    return GitHubClient(use_fixtures=True, fixtures_dir=tmp_path)


def test_strategy_update(fixtures_dir: Path, tmp_path: Path):
    client = _client_with_marker(fixtures_dir, tmp_path)
    result = upsert_pr_comment(
        client,
        owner="acme",
        repo="demo",
        pr_number=7,
        head_sha=SHA,
        report_body="hello",
        update_strategy="update",
    )
    assert result["_action"] == "update"
    assert any(c["method"] == "PATCH" for c in client.calls)


def test_strategy_skip_if_exists(fixtures_dir: Path, tmp_path: Path):
    client = _client_with_marker(fixtures_dir, tmp_path)
    result = upsert_pr_comment(
        client,
        owner="acme",
        repo="demo",
        pr_number=7,
        head_sha=SHA,
        report_body="hello",
        update_strategy="skip_if_exists",
    )
    assert result["_action"] == "skip"
    assert not any(c["method"] in ("POST", "PATCH", "DELETE") for c in client.calls)


def test_strategy_recreate(fixtures_dir: Path, tmp_path: Path):
    client = _client_with_marker(fixtures_dir, tmp_path)
    result = upsert_pr_comment(
        client,
        owner="acme",
        repo="demo",
        pr_number=7,
        head_sha=SHA,
        report_body="hello",
        update_strategy="recreate",
    )
    assert result["_action"] == "recreate"
    methods = [c["method"] for c in client.calls]
    assert "DELETE" in methods
    assert "POST" in methods
    assert summary_marker("acme", "demo", 7) in [
        c.get("body", "") for c in client.calls if c["method"] == "POST"
    ][0]
