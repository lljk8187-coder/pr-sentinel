#!/usr/bin/env python3
"""Golden score summary (M41/M44): recall / FP / LLM soft_ok from file-backed cases.

Runs rules + llm golden cases the same way as the parameterized tests.
Prints a human-readable summary to stdout.

Exit codes:
  0  always by default (score is informational; pytest assertions stay fail-fast)
     also used for ``--help`` (usage only; does not run scoring)
  2  usage / load error

Usage:
  python scripts/golden_score.py
  python scripts/golden_score.py --help
  # from repo root; uses tests/golden/{rules,llm}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="golden_score.py",
        description=(
            "Summarize golden rules/llm must_hit recall, must_not FP, and LLM soft_ok. "
            "Informational only: default exit 0 even when score is imperfect "
            "(pytest assertions remain fail-fast)."
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Override golden root (default: <repo>/tests/golden)",
    )
    return parser


def _ensure_path() -> None:
    tests = ROOT / "tests"
    for p in (ROOT, ROOT / "packages", ROOT / "packages" / "github", tests):
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)


def _finding_matches(finding, expect_item: dict) -> bool:
    if finding.rule_id != expect_item["rule_id"]:
        return False
    if (finding.filename or "") != expect_item["path"]:
        return False
    if "line" in expect_item and finding.line != expect_item["line"]:
        return False
    return True


def _any_match(findings, expect_item: dict) -> bool:
    return any(_finding_matches(f, expect_item) for f in findings)


def _response_text(response: object) -> str:
    if isinstance(response, str):
        return response
    return json.dumps(response, ensure_ascii=False)


def _score_rules(paths: list[Path], *, load_case, RulesEngine, get_default_config) -> dict:
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


def _score_llm(paths: list[Path], *, load_case, parse_llm_findings) -> dict:
    hit_ok = hit_total = 0
    fp = 0
    soft_ok = soft_total = 0
    cases = 0
    for path in paths:
        case = load_case(path)
        if case["kind"] != "llm":
            continue
        cases += 1
        findings, soft = parse_llm_findings(_response_text(case["response"]))
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


def run_score(*, golden_dir: Path | None = None) -> int:
    """Import scoring deps and print summary. Called only after argparse succeeds."""
    _ensure_path()
    from common.defaults import get_default_config
    from golden.loader import golden_root, load_case
    from pr_sentinel_github.llm import _parse_llm_findings
    from pr_sentinel_github.rules import RulesEngine

    root = golden_dir if golden_dir is not None else golden_root()
    rules_paths = sorted((root / "rules").glob("*.json"))
    llm_paths = sorted((root / "llm").glob("*.json"))
    rules = _score_rules(
        rules_paths,
        load_case=load_case,
        RulesEngine=RulesEngine,
        get_default_config=get_default_config,
    )
    llm = _score_llm(
        llm_paths,
        load_case=load_case,
        parse_llm_findings=_parse_llm_findings,
    )

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


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    # parse_args handles --help / -h: prints usage and SystemExit(0) before imports
    args = parser.parse_args(argv)
    return run_score(golden_dir=args.root)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — surface load errors clearly
        print(f"golden_score error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
