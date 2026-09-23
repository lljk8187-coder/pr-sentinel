"""Built-in defaults equivalent to `.pr-sentinel.yml` (deep-merged with repo config)."""

from __future__ import annotations

import copy
from typing import Any

# M2: in-memory defaults; worker deep_merges with default-branch `.pr-sentinel.yml`.
DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "summary_comment": True,
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
            ],
        },
        "large_files": {
            "enabled": True,
            "max_bytes": 1048576,
        },
        "weakened_tests": {
            "enabled": True,
        },
    },
    "analyzer": {
        "mode": "rules",  # fake | rules (M2 uses rules; still no LLM)
    },
}


def get_default_config() -> dict[str, Any]:
    """Return a deep-copied default config (do not mutate shared dict)."""
    return copy.deepcopy(DEFAULT_CONFIG)
