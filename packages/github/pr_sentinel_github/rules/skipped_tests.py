"""Skipped-tests rule — detect deliberate skips / focused-only runs in test paths."""

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
    "**/__tests__/**",
    "**/*.test.js",
    "**/*.test.ts",
    "**/*.test.jsx",
    "**/*.test.tsx",
    "**/*.spec.js",
    "**/*.spec.ts",
    "**/*.spec.jsx",
    "**/*.spec.tsx",
)

# Prefer known APIs; keep .skip( / .only( cautious but useful for jest/mocha variants.
_SKIP_RES: list[re.Pattern[str]] = [
    re.compile(r"pytest\.mark\.skip(?:if)?\b"),
    re.compile(r"pytest\.mark\.xfail\b"),
    re.compile(r"@unittest\.skip(?:If|Unless)?\b"),
    re.compile(r"\bself\.skipTest\s*\("),
    re.compile(r"\b(?:describe|it|test)\.only\s*\("),
    re.compile(r"\b(?:xdescribe|xit|xcontext)\s*\("),
    re.compile(r"\b(?:fdescribe|fit)\s*\("),
    re.compile(r"\.(?:skip|only)\s*\("),
]

_HUNK_RE = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@")


def _is_test_path(filename: str) -> bool:
    return any(path_matches(filename, p) for p in _TEST_PATH_PATTERNS)


def _iter_added_lines(patch: str):
    """Yield ``(new_line_no | None, content)`` for ``+`` lines (not ``+++``)."""
    next_new: int | None = None
    for raw in patch.splitlines():
        if raw.startswith("@@"):
            m = _HUNK_RE.match(raw)
            if m:
                next_new = int(m.group(1))
            continue
        if raw.startswith("\\"):
            continue
        if raw.startswith("+++") or raw.startswith("---"):
            continue
        if raw.startswith("+"):
            yield next_new, raw[1:]
            if next_new is not None:
                next_new += 1
        elif raw.startswith(" "):
            if next_new is not None:
                next_new += 1
        elif raw.startswith("-"):
            continue


class SkippedTestsRule:
    rule_id = "skipped_tests"

    def check(
        self, files: list[dict[str, Any]], config: dict[str, Any]
    ) -> list[Finding]:
        cfg = (config.get("rules") or {}).get("skipped_tests") or {}
        if not cfg.get("enabled", True):
            return []

        findings: list[Finding] = []
        for f in files:
            filename = f.get("filename") or ""
            if not _is_test_path(filename):
                continue
            patch = f.get("patch") or ""
            if not patch:
                continue
            for line_no, content in _iter_added_lines(patch):
                for rx in _SKIP_RES:
                    m = rx.search(content)
                    if m:
                        findings.append(
                            Finding(
                                rule_id=self.rule_id,
                                severity="warning",
                                message=f"检测到故意跳过/只跑用例：`{m.group(0).strip()}`",
                                filename=filename,
                                line=line_no,
                                meta={"match": m.group(0)[:80]},
                            )
                        )
                        break  # one finding per added line
        return findings
