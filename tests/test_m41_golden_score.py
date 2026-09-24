"""M41: golden_score.py runs and prints recall / soft_ok (stdlib subprocess)."""

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
