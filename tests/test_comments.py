"""Idempotent comment marker tests."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from pr_sentinel_github.analyzer import build_report
from pr_sentinel_github.client import GitHubClient, marker_for_sha
from pr_sentinel_github.comments import find_marker_comment, upsert_pr_comment

SHA = "deadbeefcafebabe000011112222333344445555"
ROOT = Path(__file__).resolve().parents[1]


def _load_worker_main():
    """Load apps/worker/main.py without colliding with apps/api/main."""
    path = ROOT / "apps" / "worker" / "main.py"
    spec = importlib.util.spec_from_file_location("pr_sentinel_worker_main", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Ensure packages resolve while loading
    for p in (ROOT, ROOT / "packages", ROOT / "packages" / "github"):
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)
    spec.loader.exec_module(mod)
    return mod


def test_marker_format():
    assert marker_for_sha(SHA) == f"<!-- pr-sentinel:{SHA} -->"


def test_find_marker_comment(fixtures_dir: Path):
    comments = json.loads((fixtures_dir / "issue_comments_with_marker.json").read_text())
    found = find_marker_comment(comments, SHA)
    assert found is not None
    assert found["id"] == 1001
    assert find_marker_comment(comments, "other-sha") is None


def test_upsert_creates_when_no_marker(fixtures_dir: Path, tmp_path: Path):
    (tmp_path / "pr_files.json").write_text((fixtures_dir / "pr_files.json").read_text())
    (tmp_path / "issue_comments.json").write_text("[]")

    client = GitHubClient(use_fixtures=True, fixtures_dir=tmp_path)
    files = client.list_pr_files("acme", "demo", 7)
    report = build_report(files, head_sha=SHA, pr_number=7)
    result = upsert_pr_comment(
        client, owner="acme", repo="demo", pr_number=7, head_sha=SHA, report_body=report
    )
    assert result["_action"] == "create"
    assert result["id"] == 9001
    posts = [c for c in client.calls if c["method"] == "POST"]
    patches = [c for c in client.calls if c["method"] == "PATCH"]
    assert len(posts) == 1
    assert len(patches) == 0
    assert marker_for_sha(SHA) in posts[0]["body"]


def test_upsert_updates_when_same_sha_exists(fixtures_dir: Path, tmp_path: Path):
    (tmp_path / "pr_files.json").write_text((fixtures_dir / "pr_files.json").read_text())
    (tmp_path / "issue_comments.json").write_text(
        (fixtures_dir / "issue_comments_with_marker.json").read_text()
    )

    client = GitHubClient(use_fixtures=True, fixtures_dir=tmp_path)
    report = build_report([], head_sha=SHA, pr_number=7)
    result = upsert_pr_comment(
        client, owner="acme", repo="demo", pr_number=7, head_sha=SHA, report_body=report
    )
    assert result["_action"] == "update"
    assert result["id"] == 1001
    posts = [c for c in client.calls if c["method"] == "POST"]
    patches = [c for c in client.calls if c["method"] == "PATCH"]
    assert len(posts) == 0
    assert len(patches) == 1
    assert marker_for_sha(SHA) in patches[0]["body"]


def test_worker_process_job_fixture_mode(fixtures_dir: Path):
    from common.settings import Settings

    worker_main = _load_worker_main()
    settings = Settings(
        use_fixtures=True,
        fixtures_dir=str(fixtures_dir),
        github_token="",
    )
    job = {
        "owner": "acme",
        "repo": "demo",
        "pr_number": 7,
        "head_sha": SHA,
        "installation_id": None,
    }
    result = worker_main.process_job(job, settings)
    assert result["_action"] == "create"
