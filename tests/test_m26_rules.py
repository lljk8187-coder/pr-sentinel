"""M26: skipped_tests + dangerous_commands rules, and secrets pattern expansion."""

from __future__ import annotations

from common.defaults import get_default_config
from pr_sentinel_github.rules import RulesEngine
from pr_sentinel_github.rules.dangerous_commands import DangerousCommandsRule
from pr_sentinel_github.rules.engine import default_rules
from pr_sentinel_github.rules.secrets import SecretsRule
from pr_sentinel_github.rules.skipped_tests import SkippedTestsRule


def _patch_added(line: str, *, start: int = 10) -> str:
    return f"@@ -{start},0 +{start},1 @@\n+{line}\n"


# --- skipped_tests ---


def test_skipped_tests_hit_pytest_mark_skip():
    files = [
        {
            "filename": "tests/test_foo.py",
            "status": "modified",
            "patch": _patch_added("    @pytest.mark.skip(reason='flaky')"),
        }
    ]
    findings = SkippedTestsRule().check(files, get_default_config())
    assert len(findings) == 1
    assert findings[0].rule_id == "skipped_tests"
    assert findings[0].severity == "warning"
    assert findings[0].line == 10
    assert "skip" in findings[0].message.lower() or "跳过" in findings[0].message


def test_skipped_tests_hit_jest_only():
    files = [
        {
            "filename": "src/__tests__/app.test.js",
            "status": "modified",
            "patch": _patch_added("  it.only('focus', () => {});"),
        }
    ]
    findings = SkippedTestsRule().check(files, get_default_config())
    assert len(findings) == 1
    assert findings[0].filename == "src/__tests__/app.test.js"


def test_skipped_tests_miss_normal_assert():
    files = [
        {
            "filename": "tests/test_ok.py",
            "status": "modified",
            "patch": _patch_added("    assert result == 1"),
        }
    ]
    assert SkippedTestsRule().check(files, get_default_config()) == []


def test_skipped_tests_path_filter_non_test():
    files = [
        {
            "filename": "src/app.py",
            "status": "modified",
            "patch": _patch_added("    @pytest.mark.skip"),
        }
    ]
    assert SkippedTestsRule().check(files, get_default_config()) == []


def test_skipped_tests_disabled():
    cfg = get_default_config()
    cfg["rules"]["skipped_tests"]["enabled"] = False
    files = [
        {
            "filename": "tests/test_foo.py",
            "status": "modified",
            "patch": _patch_added("    self.skipTest('nope')"),
        }
    ]
    assert SkippedTestsRule().check(files, cfg) == []


# --- dangerous_commands ---


def test_dangerous_commands_hit_curl_pipe_bash():
    files = [
        {
            "filename": "scripts/bootstrap.sh",
            "status": "modified",
            "patch": _patch_added("curl -fsSL https://example.com/install.sh | bash"),
        }
    ]
    findings = DangerousCommandsRule().check(files, get_default_config())
    assert len(findings) == 1
    assert findings[0].rule_id == "dangerous_commands"
    assert findings[0].severity == "error"
    assert findings[0].line == 10


def test_dangerous_commands_hit_rm_rf_root():
    files = [
        {
            "filename": "Dockerfile",
            "status": "modified",
            "patch": _patch_added("RUN rm -rf /"),
        }
    ]
    findings = DangerousCommandsRule().check(files, get_default_config())
    assert len(findings) == 1


def test_dangerous_commands_hit_chmod_777_workflow():
    files = [
        {
            "filename": ".github/workflows/ci.yml",
            "status": "modified",
            "patch": _patch_added("        run: chmod 777 /tmp/out"),
        }
    ]
    findings = DangerousCommandsRule().check(files, get_default_config())
    assert len(findings) == 1


def test_dangerous_commands_miss_safe_shell():
    files = [
        {
            "filename": "scripts/build.sh",
            "status": "modified",
            "patch": _patch_added("echo hello && make all"),
        }
    ]
    assert DangerousCommandsRule().check(files, get_default_config()) == []


def test_dangerous_commands_path_filter_python():
    """Ordinary .py must not trigger even with curl|bash."""
    files = [
        {
            "filename": "src/installer.py",
            "status": "modified",
            "patch": _patch_added('cmd = "curl https://x | bash"'),
        }
    ]
    assert DangerousCommandsRule().check(files, get_default_config()) == []


def test_dangerous_commands_disabled():
    cfg = get_default_config()
    cfg["rules"]["dangerous_commands"]["enabled"] = False
    files = [
        {
            "filename": "hack.sh",
            "status": "modified",
            "patch": _patch_added("chmod 777 /tmp"),
        }
    ]
    assert DangerousCommandsRule().check(files, cfg) == []


# --- engine wiring + secrets expansion ---


def test_default_rules_include_m26():
    ids = {r.rule_id for r in default_rules()}
    assert "skipped_tests" in ids
    assert "dangerous_commands" in ids
    engine_ids = {r.rule_id for r in RulesEngine().rules}
    assert "skipped_tests" in engine_ids
    assert "dangerous_commands" in engine_ids


def test_secrets_ghp_token():
    files = [
        {
            "filename": "config.env",
            "additions": 1,
            "patch": "@@ -0,0 +1 @@\n+TOKEN=ghp_abcdefghijklmnopqrstuvwxyz12",
        }
    ]
    findings = SecretsRule().check(files, get_default_config())
    assert any(f.rule_id == "secrets" for f in findings)
    assert any("ghp_" in (f.meta.get("match") or "") for f in findings)


def test_secrets_openai_sk():
    files = [
        {
            "filename": "secrets.txt",
            "additions": 1,
            "patch": "@@ -0,0 +1 @@\n+OPENAI_KEY=sk-abcdefghijklmnopqrstuvwxyz12",
        }
    ]
    findings = SecretsRule().check(files, get_default_config())
    assert any(f.rule_id == "secrets" for f in findings)
    assert any("sk-" in (f.meta.get("match") or "") for f in findings)
