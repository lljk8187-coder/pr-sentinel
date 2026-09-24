"""M38: golden case loader smoke — valid load + bad JSON / schema errors."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from golden.loader import GoldenCaseError, golden_root, load_case

RULES_EXAMPLE = golden_root() / "rules" / "secrets_hit_akia.json"


def test_load_valid_rules_example():
    case = load_case(RULES_EXAMPLE)
    assert case["id"] == "secrets_hit_akia"
    assert case["kind"] == "rules"
    assert isinstance(case["files"], list) and len(case["files"]) == 1
    assert case["files"][0]["filename"] == "config.env"
    assert "response" not in case
    expect = case["expect"]
    assert expect["must_hit"] == [{"rule_id": "secrets", "path": "config.env"}]
    assert expect["must_not"] == []


def test_bad_json_raises_clear_error(tmp_path: Path):
    bad = tmp_path / "broken.json"
    bad.write_text("{not-json", encoding="utf-8")
    with pytest.raises(GoldenCaseError, match="invalid JSON"):
        load_case(bad)


def test_missing_required_field_raises(tmp_path: Path):
    path = tmp_path / "no_id.json"
    path.write_text(
        json.dumps({"kind": "rules", "files": [], "expect": {"must_hit": [], "must_not": []}}),
        encoding="utf-8",
    )
    with pytest.raises(GoldenCaseError, match="missing required field 'id'"):
        load_case(path)


def test_rules_kind_requires_files(tmp_path: Path):
    path = tmp_path / "no_files.json"
    path.write_text(
        json.dumps({"id": "x", "kind": "rules", "expect": {"must_hit": [], "must_not": []}}),
        encoding="utf-8",
    )
    with pytest.raises(GoldenCaseError, match="requires 'files'"):
        load_case(path)


def test_llm_kind_requires_response(tmp_path: Path):
    path = tmp_path / "no_response.json"
    path.write_text(
        json.dumps({"id": "y", "kind": "llm", "expect": {"must_hit": [], "must_not": []}}),
        encoding="utf-8",
    )
    with pytest.raises(GoldenCaseError, match="requires 'response'"):
        load_case(path)


def test_expect_item_line_optional(tmp_path: Path):
    path = tmp_path / "with_line.json"
    path.write_text(
        json.dumps(
            {
                "id": "z",
                "kind": "llm",
                "response": {"findings": []},
                "expect": {
                    "must_hit": [{"rule_id": "llm.x", "path": "a.py", "line": 3}],
                    "must_not": [],
                },
            }
        ),
        encoding="utf-8",
    )
    case = load_case(path)
    assert case["kind"] == "llm"
    assert case["response"] == {"findings": []}
    assert case["expect"]["must_hit"] == [{"rule_id": "llm.x", "path": "a.py", "line": 3}]


def test_file_not_found():
    with pytest.raises(GoldenCaseError, match="file not found"):
        load_case(golden_root() / "rules" / "does-not-exist.json")
