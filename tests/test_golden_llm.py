"""M40: parameterized golden LLM parse cases (no live OpenAI)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pr_sentinel_github.llm import _parse_llm_findings
from pr_sentinel_github.rules.base import Finding

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from golden.loader import golden_root, load_case

LLM_DIR = golden_root() / "llm"
_CASE_PATHS = sorted(p for p in LLM_DIR.glob("*.json"))


def _response_text(response: object) -> str:
    """Normalize case.response to the raw model content string."""
    if isinstance(response, str):
        return response
    return json.dumps(response, ensure_ascii=False)


def _finding_matches(finding: Finding, expect_item: dict) -> bool:
    if finding.rule_id != expect_item["rule_id"]:
        return False
    if (finding.filename or "") != expect_item["path"]:
        return False
    if "line" in expect_item and finding.line != expect_item["line"]:
        return False
    return True


@pytest.mark.parametrize(
    "case_path",
    _CASE_PATHS,
    ids=[p.stem for p in _CASE_PATHS],
)
def test_golden_llm_case(case_path: Path):
    case = load_case(case_path)
    assert case["kind"] == "llm", f"{case_path.name}: expected kind=llm"
    content = _response_text(case["response"])
    findings, soft = _parse_llm_findings(content)

    expect = case["expect"]
    if "soft" in expect:
        assert soft is expect["soft"], (
            f"{case['id']}: soft={soft!r} expected {expect['soft']!r}"
        )
    if "findings_count" in expect:
        assert len(findings) == expect["findings_count"], (
            f"{case['id']}: findings_count={len(findings)} "
            f"expected {expect['findings_count']}"
        )

    for i, item in enumerate(expect["must_hit"]):
        assert any(_finding_matches(f, item) for f in findings), (
            f"{case['id']}: must_hit[{i}] not found: {item}; "
            f"got={[(f.rule_id, f.filename, f.line, f.message) for f in findings]}"
        )

    for i, item in enumerate(expect["must_not"]):
        assert not any(_finding_matches(f, item) for f in findings), (
            f"{case['id']}: must_not[{i}] falsely matched: {item}"
        )


def test_golden_llm_covers_core_shapes():
    """Sanity: valid / soft / empty / fenced samples present."""
    stems = {p.stem for p in _CASE_PATHS}
    required = {"valid_one_finding", "soft_bad_json", "empty_findings", "fenced_json"}
    assert required <= stems, f"missing llm golden cases: {required - stems}"
