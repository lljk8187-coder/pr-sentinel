"""M39: parameterized golden rules cases via RulesEngine + M38 loader."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from common.defaults import get_default_config
from pr_sentinel_github.rules import RulesEngine
from pr_sentinel_github.rules.base import Finding

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from golden.loader import golden_root, load_case

RULES_DIR = golden_root() / "rules"
_CASE_PATHS = sorted(RULES_DIR.glob("*.json"))


def _finding_matches(finding: Finding, expect_item: dict) -> bool:
    if finding.rule_id != expect_item["rule_id"]:
        return False
    if (finding.filename or "") != expect_item["path"]:
        return False
    if "line" in expect_item and finding.line != expect_item["line"]:
        return False
    return True


def _any_match(findings: list[Finding], expect_item: dict) -> bool:
    return any(_finding_matches(f, expect_item) for f in findings)


@pytest.mark.parametrize(
    "case_path",
    _CASE_PATHS,
    ids=[p.stem for p in _CASE_PATHS],
)
def test_golden_rules_case(case_path: Path):
    case = load_case(case_path)
    assert case["kind"] == "rules", f"{case_path.name}: expected kind=rules"
    findings, _kept, _ignored = RulesEngine().run(case["files"], get_default_config())

    for i, item in enumerate(case["expect"]["must_hit"]):
        assert _any_match(findings, item), (
            f"{case['id']}: must_hit[{i}] not found: {item}; "
            f"got={[(f.rule_id, f.filename, f.line) for f in findings]}"
        )

    for i, item in enumerate(case["expect"]["must_not"]):
        assert not _any_match(findings, item), (
            f"{case['id']}: must_not[{i}] falsely matched: {item}; "
            f"got={[(f.rule_id, f.filename, f.line) for f in findings]}"
        )


def test_golden_rules_cover_five_rule_ids():
    """Sanity: at least one hit and one miss case per built-in rule_id."""
    ids_hit: set[str] = set()
    ids_miss: set[str] = set()
    for path in _CASE_PATHS:
        case = load_case(path)
        for item in case["expect"]["must_hit"]:
            ids_hit.add(item["rule_id"])
        for item in case["expect"]["must_not"]:
            ids_miss.add(item["rule_id"])
    expected = {
        "secrets",
        "large_files",
        "weakened_tests",
        "skipped_tests",
        "dangerous_commands",
    }
    assert expected <= ids_hit, f"missing must_hit coverage: {expected - ids_hit}"
    assert expected <= ids_miss, f"missing must_not coverage: {expected - ids_miss}"
