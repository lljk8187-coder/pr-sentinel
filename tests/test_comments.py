"""Sticky summary comment + pagination truncation tests."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

from pr_sentinel_github.analyzer import build_report
from pr_sentinel_github.client import GitHubClient
from pr_sentinel_github.comments import find_summary_comment, summary_marker, upsert_pr_comment

SHA = "deadbeefcafebabe000011112222333344445555"
ROOT = Path(__file__).resolve().parents[1]


def _load_worker_main():
    path = ROOT / "apps" / "worker" / "main.py"
    spec = importlib.util.spec_from_file_location("pr_sentinel_worker_main", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    for p in (ROOT, ROOT / "packages", ROOT / "packages" / "github"):
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)
    spec.loader.exec_module(mod)
    return mod


def test_summary_marker_format():
    assert summary_marker("acme", "demo", 7) == "<!-- pr-sentinel:summary:acme/demo:7 -->"


def test_find_summary_comment(fixtures_dir: Path):
    comments = json.loads((fixtures_dir / "issue_comments_with_marker.json").read_text())
    found = find_summary_comment(comments, "acme", "demo", 7)
    assert found is not None
    assert found["id"] == 1001
    assert find_summary_comment(comments, "acme", "demo", 99) is None


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
    assert summary_marker("acme", "demo", 7) in posts[0]["body"]
    # old head_sha marker must NOT be used
    assert f"<!-- pr-sentinel:{SHA} -->" not in posts[0]["body"]


def test_upsert_updates_when_sticky_exists(fixtures_dir: Path, tmp_path: Path):
    """Same PR sticky marker → update, even if head_sha changed."""
    (tmp_path / "pr_files.json").write_text((fixtures_dir / "pr_files.json").read_text())
    (tmp_path / "issue_comments.json").write_text(
        (fixtures_dir / "issue_comments_with_marker.json").read_text()
    )

    client = GitHubClient(use_fixtures=True, fixtures_dir=tmp_path)
    new_sha = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    report = build_report([], head_sha=new_sha, pr_number=7)
    result = upsert_pr_comment(
        client, owner="acme", repo="demo", pr_number=7, head_sha=new_sha, report_body=report
    )
    assert result["_action"] == "update"
    assert result["id"] == 1001
    posts = [c for c in client.calls if c["method"] == "POST"]
    patches = [c for c in client.calls if c["method"] == "PATCH"]
    assert len(posts) == 0
    assert len(patches) == 1
    assert summary_marker("acme", "demo", 7) in patches[0]["body"]


def test_list_pr_files_truncates_max_files(fixtures_dir: Path, tmp_path: Path):
    files = [{"filename": f"f{i}.py", "additions": 1, "deletions": 0} for i in range(10)]
    (tmp_path / "pr_files.json").write_text(json.dumps(files))
    (tmp_path / "issue_comments.json").write_text("[]")
    client = GitHubClient(use_fixtures=True, fixtures_dir=tmp_path, max_files=3)
    got = client.list_pr_files("acme", "demo", 1)
    assert len(got) == 3
    assert client.truncated is True


def test_list_pr_files_pagination(monkeypatch):
    """Real HTTP path: stop after max_pages / per_page."""
    pages = {
        1: [{"filename": f"a{i}.py", "additions": 1, "deletions": 0} for i in range(2)],
        2: [{"filename": f"b{i}.py", "additions": 1, "deletions": 0} for i in range(2)],
        3: [{"filename": f"c{i}.py", "additions": 1, "deletions": 0} for i in range(2)],
    }

    class FakeResp:
        def __init__(self, data):
            self._data = data
            self.status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    class FakeHttp:
        def get(self, url, headers=None, params=None):
            page = (params or {}).get("page", 1)
            return FakeResp(pages.get(page, []))

        def close(self):
            pass

    client = GitHubClient(
        token="tok",
        use_fixtures=False,
        http_client=FakeHttp(),
        max_pages=2,
        per_page=2,
        max_files=300,
    )
    got = client.list_pr_files("acme", "demo", 1)
    assert len(got) == 4  # 2 pages × 2
    assert client.truncated is True  # page==max_pages and full page
    assert len([c for c in client.calls if c["method"] == "GET"]) == 2


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


def test_default_config_constants():
    from common.defaults import DEFAULT_CONFIG, get_default_config

    assert DEFAULT_CONFIG["analyzer"]["mode"] == "fake"
    assert DEFAULT_CONFIG["diff"]["max_files"] == 300
    cfg = get_default_config()
    cfg["analyzer"]["mode"] = "mutated"
    assert DEFAULT_CONFIG["analyzer"]["mode"] == "fake"
