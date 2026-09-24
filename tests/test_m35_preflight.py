"""M35: live preflight script — exit codes & no secret echo (stdlib subprocess)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "preflight_live.py"


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    base = {
        "PATH": os.environ.get("PATH", ""),
        "PREFLIGHT_SKIP_HEALTH": "1",
        "PREFLIGHT_DOTENV": str(ROOT / "nonexistent.env"),  # skip repo .env
    }
    base.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        env=base,
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_preflight_fail_when_fixtures_true():
    proc = _run(
        {
            "USE_FIXTURES": "true",
            "GITHUB_TOKEN": "ghp_test_token_not_real",
        }
    )
    assert proc.returncode == 1
    assert "FAIL" in proc.stdout
    assert "USE_FIXTURES=true" in proc.stdout
    assert "ghp_test_token_not_real" not in proc.stdout  # no full secret echo


def test_preflight_pass_with_pat_live():
    proc = _run(
        {
            "USE_FIXTURES": "false",
            "GITHUB_TOKEN": "ghp_test_token_not_real",
            "GITHUB_WEBHOOK_SECRET": "dev-secret",
        }
    )
    assert proc.returncode == 0
    assert "PASS" in proc.stdout
    assert "ghp_test_token_not_real" not in proc.stdout


def test_preflight_fail_missing_auth():
    proc = _run({"USE_FIXTURES": "false"})
    assert proc.returncode == 1
    assert "no live auth" in proc.stdout
