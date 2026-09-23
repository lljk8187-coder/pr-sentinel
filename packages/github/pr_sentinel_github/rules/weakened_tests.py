"""Weakened-tests rule — deleted test files or net-removed asserts."""

from __future__ import annotations

import re
from typing import Any

from .base import Finding
from .ignore_paths import path_matches

_TEST_PATH_PATTERNS = (
    "**/test_*.py",
    "**/*_test.py",
    "**/tests/**",
    "**/test/**",
)

_ASSERT_RE = re.compile(r"\bassert\b|\bself\.assert\w+\b|\bpytest\.raises\b")


def _is_test_path(filename: str) -> bool:
    return any(path_matches(filename, p) for p in _TEST_PATH_PATTERNS)


def _net_assert_delta(patch: str) -> int:
    """Net change in assert-like lines: +added -removed."""
    delta = 0
    for line in patch.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") and _ASSERT_RE.search(line[1:]):
            delta += 1
        elif line.startswith("-") and _ASSERT_RE.search(line[1:]):
            delta -= 1
    return delta


class WeakenedTestsRule:
    rule_id = "weakened_tests"

    def check(
        self, files: list[dict[str, Any]], config: dict[str, Any]
    ) -> list[Finding]:
        cfg = (config.get("rules") or {}).get("weakened_tests") or {}
        if not cfg.get("enabled", True):
            return []

        findings: list[Finding] = []
        for f in files:
            filename = f.get("filename") or ""
            status = (f.get("status") or "").lower()
            patch = f.get("patch") or ""

            if status == "removed" and _is_test_path(filename):
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        severity="warning",
                        message="删除了测试文件",
                        filename=filename,
                        meta={"status": status},
                    )
                )
                continue

            if patch and _is_test_path(filename):
                delta = _net_assert_delta(patch)
                if delta < 0:
                    findings.append(
                        Finding(
                            rule_id=self.rule_id,
                            severity="warning",
                            message=f"测试弱化：assert 净减少 {abs(delta)} 处",
                            filename=filename,
                            meta={"assert_delta": delta},
                        )
                    )
            elif patch and not _is_test_path(filename):
                # Also catch assert removals in non-test files (weaker signal)
                delta = _net_assert_delta(patch)
                if delta < 0 and status != "removed":
                    # only report if significant assert removal outside tests
                    pass
        return findings
