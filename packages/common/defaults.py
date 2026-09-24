"""Built-in defaults equivalent to `.pr-sentinel.yml` (deep-merged with repo config)."""

from __future__ import annotations

import copy
from typing import Any

# M3: in-memory defaults; worker deep_merges with default-branch `.pr-sentinel.yml`.
DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "summary_comment": True,
    "check_run": True,
    "inline_comments": True,
    "update_strategy": "update",  # update | recreate | skip_if_exists
    "ignore_paths": [
        "docs/**",
        "**/*.md",
    ],
    "diff": {
        "max_pages": 5,
        "per_page": 100,
        "max_files": 300,
    },
    "rules": {
        "secrets": {
            "enabled": True,
            "patterns": [
                r"AKIA[0-9A-Z]{16}",
                r"-----BEGIN (RSA |OPENSSH )?PRIVATE KEY-----",
                r"ghp_[A-Za-z0-9_]{20,}",
                r"sk-[A-Za-z0-9]{20,}",
            ],
        },
        "large_files": {
            "enabled": True,
            "max_bytes": 1048576,  # patch byte threshold
            "max_additions": 2000,
            "binary_extensions": [
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".webp",
                ".pdf",
                ".zip",
                ".gz",
                ".whl",
                ".exe",
                ".dll",
                ".so",
                ".dylib",
                ".bin",
            ],
        },
        "weakened_tests": {
            "enabled": True,
        },
        "skipped_tests": {
            "enabled": True,
        },
        "dangerous_commands": {
            "enabled": True,
            "patterns": [
                r"curl\b[^|\n]*\|\s*(?:ba)?sh\b",
                r"wget\b[^|\n]*\|\s*(?:ba)?sh\b",
                r"\brm\s+-[^\n]*\brf\b[^\n]*\s+/(?:\s|$|\*)",
                r"\brm\s+-[^\n]*\bfr\b[^\n]*\s+/(?:\s|$|\*)",
                r"\bchmod\s+777\b",
            ],
        },
    },
    "privacy": {
        "redact_secrets": True,
    },
    "llm": {
        "enabled": True,
        "max_patch_chars": 12000,
        "temperature": 0.2,
    },
    "analyzer": {
        # rules | rules+llm | fake — no API key → auto-degrade (skip LLM)
        "mode": "rules+llm",
    },
}


def get_default_config() -> dict[str, Any]:
    """Return a deep-copied default config (do not mutate shared dict)."""
    return copy.deepcopy(DEFAULT_CONFIG)
