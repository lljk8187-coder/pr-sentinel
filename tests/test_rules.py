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


def test_large_files_patch_too_large():
    cfg = get_default_config()
    cfg["rules"]["large_files"]["max_bytes"] = 100
    files = [
        {
            "filename": "blob.txt",
            "additions": 50,
            "deletions": 0,
            "changes": 50,
            "patch": "x" * 200,
        }
    ]
    findings = LargeFilesRule().check(files, cfg)
    assert len(findings) == 1
    assert findings[0].rule_id == "large_files"
    assert "patch_too_large" in findings[0].meta["reason"]
    assert findings[0].meta["approx_patch_bytes"] >= 100
    assert findings[0].meta["binary_or_truncated"] is False


def test_large_files_additions_too_high():
    cfg = get_default_config()
    cfg["rules"]["large_files"]["max_bytes"] = 10_000_000
    cfg["rules"]["large_files"]["max_additions"] = 100
    files = [
        {
            "filename": "big.py",
            "additions": 250,
            "deletions": 0,
            "changes": 250,
            "patch": "+line\n" * 10,  # small patch text, high additions count
        }
    ]
    findings = LargeFilesRule().check(files, cfg)
    assert len(findings) == 1
    assert "additions_too_high" in findings[0].meta["reason"]
    assert findings[0].meta["additions"] == 250


def test_large_files_binary_or_truncated_no_patch():
    cfg = get_default_config()
    files = [
        {
            "filename": "assets/logo.png",
            "additions": 0,
            "deletions": 0,
            "changes": 0,
            "patch": None,
        }
    ]
    findings = LargeFilesRule().check(files, cfg)
    assert len(findings) == 1
    assert findings[0].meta["binary_or_truncated"] is True
    assert "binary_or_truncated" in findings[0].meta["reason"]


def test_large_files_small_text_passes():
    cfg = get_default_config()
    files = [
        {
            "filename": "src/hello.py",
            "additions": 3,
            "deletions": 0,
            "changes": 3,
            "patch": "@@ -0,0 +1,3 @@\n+a\n+b\n+c\n",
        }
    ]
    findings = LargeFilesRule().check(files, cfg)
    assert findings == []


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


def test_ignore_paths_directory_prefix():
    from pr_sentinel_github.rules.ignore_paths import is_ignored

    patterns = ["vendor/**", "build/"]
    assert is_ignored("vendor/pkg/a.py", patterns)
    assert is_ignored("build/out.o", patterns)
    assert not is_ignored("src/vendor_like.py", patterns)


def test_ignore_paths_glob_starstar():
    from pr_sentinel_github.rules.ignore_paths import is_ignored

    patterns = ["**/*.generated.ts", "**/fixtures/**"]
    assert is_ignored("api/types.generated.ts", patterns)
    assert is_ignored("pkg/fixtures/sample.json", patterns)
    assert not is_ignored("api/types.ts", patterns)


def test_ignore_paths_negation():
    from pr_sentinel_github.rules.ignore_paths import is_ignored

    patterns = ["**/*.md", "!README.md", "!docs/KEEP.md"]
    assert is_ignored("notes.md", patterns)
    assert not is_ignored("README.md", patterns)
    assert not is_ignored("docs/KEEP.md", patterns)
    assert is_ignored("docs/other.md", patterns)


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
