"""M8: Check Run conclusion/annotations + inline comments + worker wiring."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from common.defaults import DEFAULT_CONFIG, get_default_config
from common.settings import Settings
from pr_sentinel_github.check_runs import (
    MAX_ANNOTATIONS,
    conclusion_for_findings,
    findings_to_annotations,
    publish_check_run,
    publish_inline_comments,
)
from pr_sentinel_github.client import GitHubClient
from pr_sentinel_github.rules.base import Finding
from pr_sentinel_github.rules.patch_lines import patch_offset_to_new_line
from pr_sentinel_github.rules.secrets import SecretsRule

SHA = "deadbeefcafebabe000011112222333344445555"
ROOT = Path(__file__).resolve().parents[1]


def _load_worker_main():
    path = ROOT / "apps" / "worker" / "main.py"
    spec = importlib.util.spec_from_file_location("pr_sentinel_worker_main_m8", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    for p in (ROOT, ROOT / "packages", ROOT / "packages" / "github"):
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)
    spec.loader.exec_module(mod)
    return mod


def _f(**kwargs) -> Finding:
    base: dict = {"rule_id": "t", "severity": "info", "message": "m"}
    base.update(kwargs)
    return Finding(**base)


def test_conclusion_success_without_high():
    findings = [
        _f(severity="info"),
        _f(severity="warning"),
        _f(severity="medium"),
        _f(severity="low"),
    ]
    assert conclusion_for_findings(findings) == "success"
    assert conclusion_for_findings([]) == "success"


def test_conclusion_failure_on_error_high_critical():
    assert conclusion_for_findings([_f(severity="error")]) == "failure"
    assert conclusion_for_findings([_f(severity="high")]) == "failure"
    assert conclusion_for_findings([_f(severity="critical")]) == "failure"
    assert (
        conclusion_for_findings([_f(severity="info"), _f(severity="critical")])
        == "failure"
    )


def test_annotations_cap_50_and_truncate_count():
    findings = [
        _f(severity="warning", message=f"f{i}", filename=f"a/{i}.py", line=i + 1)
        for i in range(60)
    ]
    annos, truncated = findings_to_annotations(findings)
    assert len(annos) == MAX_ANNOTATIONS == 50
    assert truncated == 10
    assert annos[0]["path"] == "a/0.py"
    assert annos[0]["start_line"] == 1
    assert annos[0]["annotation_level"] == "warning"


def test_annotations_skip_missing_path_or_line():
    findings = [
        _f(severity="error", filename="a.py", line=None),
        _f(severity="error", filename=None, line=3),
        _f(severity="error", filename="b.py", line=2),
    ]
    annos, truncated = findings_to_annotations(findings)
    assert len(annos) == 1
    assert truncated == 0
    assert annos[0]["path"] == "b.py"
    assert annos[0]["annotation_level"] == "failure"


def test_inline_only_high_with_line(tmp_path: Path):
    (tmp_path / "pr_files.json").write_text("[]")
    (tmp_path / "issue_comments.json").write_text("[]")
    client = GitHubClient(use_fixtures=True, fixtures_dir=tmp_path)
    findings = [
        _f(severity="warning", filename="a.py", line=1, message="warn"),
        _f(severity="high", filename="b.py", line=2, message="hi"),
        _f(severity="error", filename="c.py", line=None, message="no-line"),
        _f(severity="critical", filename="d.py", line=4, message="crit"),
        _f(severity="info", filename="e.py", line=5, message="info"),
    ]
    results = publish_inline_comments(
        client,
        owner="acme",
        repo="demo",
        pr_number=7,
        head_sha=SHA,
        findings=findings,
    )
    assert len(results) == 2
    assert {r["path"] for r in results} == {"b.py", "d.py"}
    posts = [
        c
        for c in client.calls
        if c["method"] == "POST"
        and "/pulls/" in c.get("path", "")
        and str(c.get("path", "")).endswith("/comments")
    ]
    assert len(posts) == 2


def test_publish_check_run_fixture_calls(tmp_path: Path):
    (tmp_path / "pr_files.json").write_text("[]")
    (tmp_path / "issue_comments.json").write_text("[]")
    client = GitHubClient(use_fixtures=True, fixtures_dir=tmp_path)
    findings = [
        _f(severity="error", filename="sec.py", line=3, message="secret"),
        _f(severity="info", filename="ok.py", line=None, message="ok"),
    ]
    result = publish_check_run(
        client,
        owner="acme",
        repo="demo",
        head_sha=SHA,
        findings=findings,
        report_body="## report",
    )
    assert result["_conclusion"] == "failure"
    assert result["_annotations"] == 1
    post = next(c for c in client.calls if c["method"] == "POST" and "check-runs" in c["path"])
    patch = next(c for c in client.calls if c["method"] == "PATCH" and "check-runs" in c["path"])
    assert post["payload"]["status"] == "in_progress"
    assert patch["payload"]["status"] == "completed"
    assert patch["payload"]["conclusion"] == "failure"
    assert len(patch["payload"]["output"]["annotations"]) == 1


def test_defaults_include_check_run_and_inline():
    assert DEFAULT_CONFIG["check_run"] is True
    assert DEFAULT_CONFIG["inline_comments"] is True
    cfg = get_default_config()
    assert cfg["check_run"] is True
    assert cfg["inline_comments"] is True


def test_secrets_sets_line_from_patch():
    files = [
        {
            "filename": "config.env",
            "additions": 1,
            "deletions": 0,
            "patch": "@@ -0,0 +1,1 @@\n+AWS_KEY=AKIAIOSFODNN7EXAMPLE\n",
        }
    ]
    findings = SecretsRule().check(files, get_default_config())
    assert len(findings) >= 1
    assert findings[0].line == 1


def test_patch_offset_helper():
    patch = "@@ -1,2 +1,3 @@\n context\n-old\n+AKIAIOSFODNN7EXAMPLE\n"
    idx = patch.index("AKIA")
    assert patch_offset_to_new_line(patch, idx) == 2


def test_worker_summary_comment_false_still_creates_check_run(
    fixtures_dir: Path, tmp_path: Path
):
    (tmp_path / "pr-sentinel.yml").write_text(
        "\n".join(
            [
                "version: 1",
                "summary_comment: false",
                "check_run: true",
                "inline_comments: false",
                "analyzer:",
                "  mode: fake",
            ]
        )
        + "\n"
    )
    (tmp_path / "pr_files.json").write_text((fixtures_dir / "pr_files.json").read_text())
    (tmp_path / "issue_comments.json").write_text("[]")
    (tmp_path / "repo.json").write_text(json.dumps({"default_branch": "main"}))

    worker_main = _load_worker_main()
    settings = Settings(
        use_fixtures=True,
        fixtures_dir=str(tmp_path),
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
    assert result["_action"] == "skipped_comment"
    assert "check_run" in result
    assert result["check_run"].get("id")
    assert result.get("inline_comments") in (None, [])
