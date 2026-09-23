"""Ignore-path filtering (fnmatch / glob) applied before other rules."""

from __future__ import annotations

import fnmatch
from typing import Any


def path_matches(filename: str, pattern: str) -> bool:
    """Match *filename* against a gitignore-ish glob pattern via fnmatch.

    Supports common cases: ``*.md``, ``**/*.md``, ``docs/**``, ``**/tests/**``.
    """
    name = filename.lstrip("./")
    candidates = [pattern]

    # ``**/foo`` also matches ``foo`` at repo root
    if pattern.startswith("**/"):
        candidates.append(pattern[3:])

    # ``docs/**`` → prefix match
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        if name == prefix or name.startswith(prefix + "/"):
            return True

    for pat in candidates:
        if fnmatch.fnmatch(name, pat):
            return True
        # Match against each path suffix (dir/file components)
        parts = name.split("/")
        for i in range(len(parts)):
            sub = "/".join(parts[i:])
            if fnmatch.fnmatch(sub, pat):
                return True
            # Also try basename-only for patterns like *.md
            if fnmatch.fnmatch(parts[-1], pat):
                return True
    return False


def is_ignored(filename: str, ignore_paths: list[str]) -> bool:
    for pat in ignore_paths:
        if path_matches(filename, pat):
            return True
    return False


def filter_ignored(
    files: list[dict[str, Any]], config: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split files into (kept, ignored) based on ``config['ignore_paths']``."""
    patterns = list(config.get("ignore_paths") or [])
    kept: list[dict[str, Any]] = []
    ignored: list[dict[str, Any]] = []
    for f in files:
        name = f.get("filename") or ""
        if is_ignored(name, patterns):
            ignored.append(f)
        else:
            kept.append(f)
    return kept, ignored
