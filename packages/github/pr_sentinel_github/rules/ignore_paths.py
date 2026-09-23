"""Ignore-path filtering via pathspec GitIgnoreSpec (gitignore semantics)."""

from __future__ import annotations

from typing import Any

from pathspec import GitIgnoreSpec


def _normalize(filename: str) -> str:
    return (filename or "").lstrip("./")


def _compile(patterns: list[str]) -> GitIgnoreSpec | None:
    cleaned = [p for p in patterns if p is not None and str(p).strip() != ""]
    if not cleaned:
        return None
    return GitIgnoreSpec.from_lines(cleaned)


def path_matches(filename: str, pattern: str) -> bool:
    """Match *filename* against a single gitignore-style pattern.

    Used by other rules (e.g. weakened_tests) for path glob checks.
    """
    if not pattern:
        return False
    spec = _compile([pattern])
    if spec is None:
        return False
    return spec.match_file(_normalize(filename))


def is_ignored(filename: str, ignore_paths: list[str]) -> bool:
    """Return True if *filename* is ignored by the full pattern list.

    Patterns are compiled together so gitignore negation (``!``) works.
    """
    spec = _compile(list(ignore_paths or []))
    if spec is None:
        return False
    return spec.match_file(_normalize(filename))


def filter_ignored(
    files: list[dict[str, Any]], config: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split files into (kept, ignored) based on ``config['ignore_paths']``."""
    patterns = list(config.get("ignore_paths") or [])
    spec = _compile(patterns)
    kept: list[dict[str, Any]] = []
    ignored: list[dict[str, Any]] = []
    for f in files:
        name = f.get("filename") or ""
        if spec is not None and spec.match_file(_normalize(name)):
            ignored.append(f)
        else:
            kept.append(f)
    return kept, ignored
