"""M41/M44: golden_score.py summary + --help (stdlib subprocess)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "golden_score.py"


def test_golden_score_script_exits_zero_and_prints_summary():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    out = proc.stdout
    assert "must_hit recall" in out
    assert "must_not FP" in out
    assert "soft_ok" in out
    assert "[rules]" in out and "[llm]" in out


def test_golden_score_help_exits_zero_without_scoring():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        env={**os.environ},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    help_text = proc.stdout + proc.stderr
    assert "usage" in help_text.lower()
    # Help/description may mention metrics; scoring body must not run.
    assert "[rules]" not in help_text
    assert "golden root:" not in help_text
    assert "soft_ok:" not in help_text
