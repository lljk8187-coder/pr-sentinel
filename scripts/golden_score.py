#!/usr/bin/env python3
"""Golden score summary (M41): recall / FP / LLM soft_ok from file-backed cases.

Runs rules + llm golden cases the same way as the parameterized tests.
Prints a human-readable summary to stdout.

Exit codes:
  0  always by default (score is informational; pytest assertions stay fail-fast)
  2  usage / load error

Usage:
  python scripts/golden_score.py
  # from repo root; uses tests/golden/{rules,llm}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
for p in (ROOT, ROOT / "packages", ROOT / "packages" / "github", TESTS):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from common.defaults import get_default_config  # noqa: E402
from golden.loader import golden_root, load_case  # noqa: E402
from pr_sentinel_github.llm import _parse_llm_findings  # noqa: E402
from pr_sentinel_github.rules import RulesEngine  # noqa: E402
from pr_sentinel_github.rules.base import Finding  # noqa: E402


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


def _response_text(response: object) -> str:
    if isinstance(response, str):
        return response
    return json.dumps(response, ensure_ascii=False)


def _score_rules(paths: list[Path]) -> dict:
    hit_ok = hit_total = 0
    fp = 0
    cases = 0
    for path in paths:
        case = load_case(path)
        if case["kind"] != "rules":
            continue
        cases += 1
        findings, _kept, _ignored = RulesEngine().run(case["files"], get_default_config())
        for item in case["expect"]["must_hit"]:
            hit_total += 1
            if _any_match(findings, item):
                hit_ok += 1
        for item in case["expect"]["must_not"]:
            if _any_match(findings, item):
                fp += 1
    recall = (hit_ok / hit_total) if hit_total else 1.0
    return {
        "cases": cases,
        "must_hit_ok": hit_ok,
        "must_hit_total": hit_total,
        "recall": recall,
        "must_not_fp": fp,
    }


def _score_llm(paths: list[Path]) -> dict:
    hit_ok = hit_total = 0
    fp = 0
    soft_ok = soft_total = 0
    cases = 0
    for path in paths:
        case = load_case(path)
        if case["kind"] != "llm":
            continue
        cases += 1
        findings, soft = _parse_llm_findings(_response_text(case["response"]))
        expect = case["expect"]
        if "soft" in expect:
            soft_total += 1
            if soft is expect["soft"]:
                soft_ok += 1
        for item in expect["must_hit"]:
            hit_total += 1
            if _any_match(findings, item):
                hit_ok += 1
        for item in expect["must_not"]:
            if _any_match(findings, item):
                fp += 1
    recall = (hit_ok / hit_total) if hit_total else 1.0
    soft_rate = (soft_ok / soft_total) if soft_total else 1.0
    return {
        "cases": cases,
        "must_hit_ok": hit_ok,
        "must_hit_total": hit_total,
        "recall": recall,
        "must_not_fp": fp,
        "soft_ok": soft_ok,
        "soft_total": soft_total,
        "soft_rate": soft_rate,
    }


def main() -> int:
    root = golden_root()
    rules_paths = sorted((root / "rules").glob("*.json"))
    llm_paths = sorted((root / "llm").glob("*.json"))
    rules = _score_rules(rules_paths)
    llm = _score_llm(llm_paths)

    print("=== pr-sentinel golden score (M41) ===")
    print(f"golden root: {root}")
    print()
    print("[rules]")
    print(f"  cases:          {rules['cases']}")
    print(
        f"  must_hit recall: {rules['must_hit_ok']}/{rules['must_hit_total']} "
        f"({rules['recall']:.1%})"
    )
    print(f"  must_not FP:    {rules['must_not_fp']}")
    print()
    print("[llm]")
    print(f"  cases:          {llm['cases']}")
    print(
        f"  must_hit recall: {llm['must_hit_ok']}/{llm['must_hit_total']} "
        f"({llm['recall']:.1%})"
    )
    print(f"  must_not FP:    {llm['must_not_fp']}")
    print(
        f"  soft_ok:        {llm['soft_ok']}/{llm['soft_total']} "
        f"({llm['soft_rate']:.1%})"
    )
    print()
    print("Note: score is informational; default exit 0 (pytest stays fail-fast).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 — surface load errors clearly
        print(f"golden_score error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
