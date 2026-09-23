"""Rule engine unit tests: secrets, large_files, weakened_tests, ignore_paths."""

from __future__ import annotations

from common.defaults import get_default_config
from pr_sentinel_github.analyzer import RulesAnalyzer, build_rules_report
from pr_sentinel_github.rules import RulesEngine, filter_ignored
from pr_sentinel_github.rules.large_files import LargeFilesRule
from pr_sentinel_github.rules.secrets import SecretsRule
from pr_sentinel_github.rules.weakened_tests import WeakenedTestsRule


def test_secrets_rule_detects_akia():
    files = [
        {
            "filename": "config.env",
            "additions": 1,
            "deletions": 0,
            "patch": "@@ -0,0 +1 @@\n+AWS_KEY=AKIAIOSFODNN7EXAMPLE",
        }
    ]
    findings = SecretsRule().check(files, get_default_config())
    assert len(findings) >= 1
    assert findings[0].rule_id == "secrets"
    assert findings[0].severity == "error"


def test_large_files_rule():
    cfg = get_default_config()
    cfg["rules"]["large_files"]["max_bytes"] = 100
    files = [
        {
            "filename": "blob.bin",
            "additions": 50,
            "deletions": 0,
            "changes": 50,
            "patch": "x" * 200,
        }
    ]
    findings = LargeFilesRule().check(files, cfg)
    assert len(findings) == 1
    assert findings[0].rule_id == "large_files"


def test_weakened_tests_deleted_file():
    files = [
        {
            "filename": "tests/test_foo.py",
            "status": "removed",
            "additions": 0,
            "deletions": 20,
            "patch": "",
        }
    ]
    findings = WeakenedTestsRule().check(files, get_default_config())
    assert len(findings) == 1
    assert "删除" in findings[0].message


def test_weakened_tests_assert_removal():
    files = [
        {
            "filename": "tests/test_bar.py",
            "status": "modified",
            "additions": 0,
            "deletions": 2,
            "patch": "@@ -1,3 +1,1 @@\n-    assert result == 1\n-    assert ok\n     pass\n",
        }
    ]
    findings = WeakenedTestsRule().check(files, get_default_config())
    assert len(findings) == 1
    assert findings[0].meta.get("assert_delta", 0) < 0


def test_ignore_paths_filters_md():
    cfg = get_default_config()
    files = [
        {"filename": "README.md", "additions": 1},
        {"filename": "src/app.py", "additions": 1},
        {"filename": "docs/guide.txt", "additions": 1},
    ]
    kept, ignored = filter_ignored(files, cfg)
    names_kept = {f["filename"] for f in kept}
    names_ign = {f["filename"] for f in ignored}
    assert "src/app.py" in names_kept
    assert "README.md" in names_ign
    assert "docs/guide.txt" in names_ign


def test_engine_skips_ignored_for_secrets():
    cfg = get_default_config()
    files = [
        {
            "filename": "notes.md",
            "additions": 1,
            "patch": "+AKIAIOSFODNN7EXAMPLE",
        },
        {
            "filename": "src/keys.py",
            "additions": 1,
            "patch": "+AKIAIOSFODNN7EXAMPLE",
        },
    ]
    findings, kept, ignored = RulesEngine().run(files, cfg)
    assert any(f["filename"] == "notes.md" for f in ignored)
    assert all(f.filename != "notes.md" for f in findings)
    assert any(f.filename == "src/keys.py" for f in findings)


def test_rules_analyzer_report_mentions_truncation():
    report = RulesAnalyzer().analyze(
        [],
        head_sha="deadbeefcafebabe000011112222333344445555",
        pr_number=1,
        truncated=True,
        config=get_default_config(),
        config_notes=["测试 note"],
    )
    assert "Limits 截断" in report
    assert "测试 note" in report
