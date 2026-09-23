"""Built-in defaults equivalent to a future `.pr-sentinel.yml` (M1: no repo file read)."""

from __future__ import annotations

from typing import Any

# M1: in-memory defaults only. M2+ may load `.pr-sentinel.yml` from the PR head.
DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "summary_comment": True,
    "diff": {
        "max_pages": 5,
        "per_page": 100,
        "max_files": 300,
    },
    "analyzer": {
        "mode": "fake",  # M1 fixed fake report; M2+ LLM / rules
    },
}


def get_default_config() -> dict[str, Any]:
    """Return a shallow-copied default config (do not mutate shared dict)."""
    import copy

    return copy.deepcopy(DEFAULT_CONFIG)
