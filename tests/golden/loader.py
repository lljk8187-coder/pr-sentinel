"""Golden case loader for Phase10 sampling (M38).

JSON cases live under ``tests/golden/rules/`` and ``tests/golden/llm/``.
This module only loads and validates shape; runners come in later milestones.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class GoldenCaseError(ValueError):
    """Invalid golden case JSON or schema."""


_REQUIRED_TOP = ("id", "kind", "expect")
_KINDS = frozenset({"rules", "llm"})


def _require_str(obj: dict[str, Any], key: str, *, ctx: str) -> str:
    val = obj.get(key)
    if not isinstance(val, str) or not val.strip():
        raise GoldenCaseError(f"{ctx}: missing or empty string field {key!r}")
    return val


def _normalize_expect_item(item: Any, *, ctx: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise GoldenCaseError(f"{ctx}: expect item must be an object, got {type(item).__name__}")
    rule_id = _require_str(item, "rule_id", ctx=ctx)
    path = _require_str(item, "path", ctx=ctx)
    out: dict[str, Any] = {"rule_id": rule_id, "path": path}
    if "line" in item and item["line"] is not None:
        if not isinstance(item["line"], int) or isinstance(item["line"], bool):
            raise GoldenCaseError(f"{ctx}: line must be an int when present")
        out["line"] = item["line"]
    return out


def _normalize_expect(raw: Any, *, ctx: str) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(raw, dict):
        raise GoldenCaseError(f"{ctx}: expect must be an object")
    must_hit = raw.get("must_hit", [])
    must_not = raw.get("must_not", [])
    if not isinstance(must_hit, list):
        raise GoldenCaseError(f"{ctx}: expect.must_hit must be a list")
    if not isinstance(must_not, list):
        raise GoldenCaseError(f"{ctx}: expect.must_not must be a list")
    out: dict[str, Any] = {
        "must_hit": [
            _normalize_expect_item(x, ctx=f"{ctx}.must_hit[{i}]") for i, x in enumerate(must_hit)
        ],
        "must_not": [
            _normalize_expect_item(x, ctx=f"{ctx}.must_not[{i}]") for i, x in enumerate(must_not)
        ],
    }
    if "soft" in raw:
        if not isinstance(raw["soft"], bool):
            raise GoldenCaseError(f"{ctx}: expect.soft must be a bool when present")
        out["soft"] = raw["soft"]
    if "findings_count" in raw:
        if not isinstance(raw["findings_count"], int) or isinstance(raw["findings_count"], bool):
            raise GoldenCaseError(f"{ctx}: expect.findings_count must be an int when present")
        out["findings_count"] = raw["findings_count"]
    return out


def load_case(path: str | Path) -> dict[str, Any]:
    """Load one golden case from a JSON file.

    Returns a dict with keys ``id``, ``kind``, ``expect``, and either
    ``files`` (kind=rules) or ``response`` (kind=llm).

    Raises:
        GoldenCaseError: unreadable path, bad JSON, or schema violations.
        FileNotFoundError: path does not exist (also wrapped message via GoldenCaseError
            when useful — we prefer GoldenCaseError for all loader failures).
    """
    p = Path(path)
    ctx = str(p)
    if not p.is_file():
        raise GoldenCaseError(f"{ctx}: file not found")
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise GoldenCaseError(f"{ctx}: cannot read file: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GoldenCaseError(f"{ctx}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise GoldenCaseError(f"{ctx}: top-level JSON must be an object")

    for key in _REQUIRED_TOP:
        if key not in data:
            raise GoldenCaseError(f"{ctx}: missing required field {key!r}")

    case_id = _require_str(data, "id", ctx=ctx)
    kind = _require_str(data, "kind", ctx=ctx)
    if kind not in _KINDS:
        raise GoldenCaseError(f"{ctx}: kind must be one of {sorted(_KINDS)}, got {kind!r}")

    expect = _normalize_expect(data["expect"], ctx=f"{ctx}.expect")

    out: dict[str, Any] = {"id": case_id, "kind": kind, "expect": expect}

    if kind == "rules":
        files = data.get("files")
        if not isinstance(files, list):
            raise GoldenCaseError(f"{ctx}: kind=rules requires 'files' as a list")
        out["files"] = files
    else:  # llm
        if "response" not in data:
            raise GoldenCaseError(f"{ctx}: kind=llm requires 'response'")
        out["response"] = data["response"]

    return out


def golden_root() -> Path:
    """Directory containing ``rules/`` and ``llm/`` case trees."""
    return Path(__file__).resolve().parent
