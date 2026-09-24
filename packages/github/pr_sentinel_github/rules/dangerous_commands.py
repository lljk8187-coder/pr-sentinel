"""Dangerous-commands rule — high-risk shell patterns in scripts / CI / Docker."""

from __future__ import annotations

import re
from typing import Any

from .base import Finding
from .ignore_paths import path_matches

_SCRIPT_PATH_PATTERNS = (
    "**/*.sh",
    "**/*.bash",
    "**/Dockerfile",
    "**/Dockerfile.*",
    "**/*Dockerfile*",
    "**/docker-compose*.yml",
    "**/docker-compose*.yaml",
    "**/*docker-compose*.yml",
    "**/*docker-compose*.yaml",
    "**/.github/workflows/**",
    "**/*.yml",
    "**/*.yaml",
    "**/Makefile",
    "**/makefile",
    "**/GNUmakefile",
)

_DEFAULT_PATTERNS = [
    r"curl\b[^|\n]*\|\s*(?:ba)?sh\b",
    r"wget\b[^|\n]*\|\s*(?:ba)?sh\b",
    r"\brm\s+-[^\n]*\brf\b[^\n]*\s+/(?:\s|$|\*)",
    r"\brm\s+-[^\n]*\bfr\b[^\n]*\s+/(?:\s|$|\*)",
    r"\bchmod\s+777\b",
]

_HUNK_RE = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@")


def _is_script_path(filename: str) -> bool:
    return any(path_matches(filename, p) for p in _SCRIPT_PATH_PATTERNS)


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


class DangerousCommandsRule:
    rule_id = "dangerous_commands"

    def check(
        self, files: list[dict[str, Any]], config: dict[str, Any]
    ) -> list[Finding]:
        cfg = (config.get("rules") or {}).get("dangerous_commands") or {}
        if not cfg.get("enabled", True):
            return []

        patterns = list(cfg.get("patterns") or _DEFAULT_PATTERNS)
        compiled: list[re.Pattern[str]] = []
        for p in patterns:
            try:
                compiled.append(re.compile(p))
            except re.error:
                continue
        if not compiled:
            return []

        findings: list[Finding] = []
        for f in files:
            filename = f.get("filename") or ""
            if not _is_script_path(filename):
                continue
            patch = f.get("patch") or ""
            if not patch:
                continue
            for line_no, content in _iter_added_lines(patch):
                for rx in compiled:
                    m = rx.search(content)
                    if m:
                        findings.append(
                            Finding(
                                rule_id=self.rule_id,
                                severity="error",
                                message=f"检测到高危命令模式：`{m.group(0).strip()[:60]}`",
                                filename=filename,
                                line=line_no,
                                meta={
                                    "match": m.group(0)[:80],
                                    "pattern": rx.pattern,
                                },
                            )
                        )
                        break  # one finding per added line
        return findings
