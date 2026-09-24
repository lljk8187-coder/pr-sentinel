"""Analyzers: FakeAnalyzer (M1) + RulesAnalyzer (M2) + RulesLLMAnalyzer (M3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .findings_merge import merge_findings
from .llm import LLMReviewResult, max_severity, review_with_llm
from .rules import Finding, RulesEngine


@dataclass
class AnalysisResult:
    """Structured analyzer output for the worker (markdown + findings)."""

    markdown: str
    findings: list[Finding]
    overall_severity: str


def build_report(
    files: list[dict[str, Any]],
    *,
    head_sha: str,
    pr_number: int,
    truncated: bool = False,
    config: dict[str, Any] | None = None,
) -> str:
    """Build a fixed fake quality-gate report from PR file list (M1 compat)."""
    names = [f.get("filename", "?") for f in files]
    additions = sum(int(f.get("additions", 0)) for f in files)
    deletions = sum(int(f.get("deletions", 0)) for f in files)
    file_list = "\n".join(f"- `{n}`" for n in names[:50]) or "- (no files)"
    if len(names) > 50:
        file_list += f"\n- … 另有 {len(names) - 50} 个文件未列出"

    trunc_note = ""
    if truncated:
        trunc_note = "\n\n> ⚠️ **Limits 截断**：Diff 已按 `max_pages` / `max_files` 截断，报告可能不完整。\n"

    mode = (config or {}).get("analyzer", {}).get("mode", "fake")

    return (
        f"## PR Sentinel — 假分析报告\n\n"
        f"**PR** #{pr_number} · **SHA** `{head_sha[:12]}` · **mode** `{mode}`\n\n"
        f"| 指标 | 值 |\n| --- | --- |\n"
        f"| 改动文件数 | {len(files)} |\n"
        f"| +行 | {additions} |\n"
        f"| -行 | {deletions} |\n"
        f"| 截断 | {'是' if truncated else '否'} |\n\n"
        f"### 文件列表\n{file_list}\n"
        f"{trunc_note}\n"
        f"> FakeAnalyzer 固定报告（无 LLM）。\n"
    )



def _severity_rank_local(severity: str) -> int:
    return {
        "critical": 4,
        "error": 3,
        "high": 3,
        "warning": 2,
        "medium": 2,
        "info": 1,
        "low": 1,
    }.get((severity or "info").lower(), 1)


def _sort_findings_by_severity(items: list[Finding]) -> list[Finding]:
    """Higher severity first (error > warning > info / aliases)."""
    return sorted(
        items,
        key=lambda f: (
            -_severity_rank_local(f.severity),
            f.rule_id or "",
            f.filename or "",
            f.line if f.line is not None else -1,
        ),
    )


def _severity_emoji(severity: str) -> str:
    return {
        "critical": "🛑",
        "error": "🛑",
        "high": "🛑",
        "warning": "⚠️",
        "medium": "⚠️",
        "info": "ℹ️",
        "low": "ℹ️",
    }.get(severity, "•")


def _format_finding_line(item: Finding) -> str:
    loc = f"`{item.filename}` — " if item.filename else ""
    line = (
        f"- {_severity_emoji(item.severity)} **{item.severity}** "
        f"{loc}{item.message}"
    )
    if item.detail:
        line += f"\n  - {item.detail}"
    return line


def build_rules_report(
    files: list[dict[str, Any]],
    *,
    head_sha: str,
    pr_number: int,
    truncated: bool = False,
    config: dict[str, Any] | None = None,
    findings: list[Finding] | None = None,
    ignored_files: list[dict[str, Any]] | None = None,
    config_notes: list[str] | None = None,
    llm_result: LLMReviewResult | None = None,
) -> str:
    """Markdown report: overview / severity / rules / LLM / assumptions / limits."""
    cfg = config or {}
    mode = cfg.get("analyzer", {}).get("mode", "rules")
    findings = findings or []
    ignored_files = ignored_files or []
    config_notes = config_notes or []

    rule_findings = [f for f in findings if f.source != "llm"]
    llm_findings = [f for f in findings if f.source == "llm"]
    if llm_result is not None:
        llm_findings = list(llm_result.findings)

    all_for_sev = list(rule_findings) + list(llm_findings)
    overall = max_severity(all_for_sev, default="info")

    additions = sum(int(f.get("additions", 0)) for f in files)
    deletions = sum(int(f.get("deletions", 0)) for f in files)

    lines: list[str] = [
        "## PR Sentinel — 质量闸门报告",
        "",
        f"**PR** #{pr_number} · **SHA** `{head_sha[:12]}` · **mode** `{mode}` · "
        f"**severity** `{overall}` {_severity_emoji(overall)}",
        "",
        "### 总览",
        "",
        "| 指标 | 值 |",
        "| --- | --- |",
        f"| 分析文件数 | {len(files)} |",
        f"| 忽略文件数 | {len(ignored_files)} |",
        f"| 规则 Findings | {len(rule_findings)} |",
        f"| LLM Findings | {len(llm_findings)} |",
        f"| 总体 severity | `{overall}` |",
        f"| +行 | {additions} |",
        f"| -行 | {deletions} |",
        f"| 截断 | {'是' if truncated else '否'} |",
        "",
    ]

    if config_notes:
        lines.append("### 配置")
        for note in config_notes:
            lines.append(f"- {note}")
        lines.append("")

    if truncated:
        lines.append(
            "> ⚠️ **Limits 截断声明**：Diff 已按配置的 `diff.max_pages` / "
            "`diff.max_files`（或环境变量）截断，后续规则/LLM 仅基于已拉取文件，报告可能不完整。"
        )
        lines.append("")

    lines.append("### 规则发现")
    if not rule_findings:
        lines.append("无发现问题。")
        lines.append("")
    else:
        by_rule: dict[str, list[Finding]] = {}
        for fnd in rule_findings:
            by_rule.setdefault(fnd.rule_id, []).append(fnd)
        for rule_id, items in by_rule.items():
            lines.append(f"#### `{rule_id}` ({len(items)})")
            for item in _sort_findings_by_severity(items):
                lines.append(_format_finding_line(item))
            lines.append("")

    # Backward-compat heading used by older M2 wording in some tests
    # (tests assert "Limits 截断" and findings content, not "### Findings")

    lines.append("### LLM 发现")
    if mode not in ("rules+llm",):
        lines.append("_mode 非 `rules+llm`，未调用 LLM。_")
    elif llm_result is not None and llm_result.skipped:
        reason = llm_result.skip_reason or "unknown"
        lines.append(f"_LLM 已跳过_（`llm_skipped: true`）：{reason}")
    elif not llm_findings:
        lines.append("无 LLM 发现问题。")
    else:
        for item in _sort_findings_by_severity(llm_findings):
            lines.append(_format_finding_line(item))
    lines.append("")

    assumptions: list[str] = []
    if llm_result is not None:
        assumptions.extend(llm_result.assumptions)
    if assumptions:
        lines.append("### Assumptions / uncertainties")
        for a in assumptions:
            lines.append(f"- {a}")
        lines.append("")

    if ignored_files:
        names = [f.get("filename", "?") for f in ignored_files[:30]]
        lines.append("### 已忽略路径")
        for n in names:
            lines.append(f"- `{n}`")
        if len(ignored_files) > 30:
            lines.append(f"- … 另有 {len(ignored_files) - 30} 个")
        lines.append("")

    if mode == "rules+llm":
        footer = "Rules+LLM Analyzer"
    elif mode == "fake":
        footer = "FakeAnalyzer"
    else:
        footer = "RulesAnalyzer"
    lines.append(
        f"> {footer}。配置来自 default branch `.pr-sentinel.yml` 与 DEFAULT_CONFIG 深度合并。"
    )
    lines.append("")
    return "\n".join(lines)


class FakeAnalyzer:
    def analyze(
        self,
        files: list[dict[str, Any]],
        *,
        head_sha: str,
        pr_number: int,
        truncated: bool = False,
        config: dict[str, Any] | None = None,
        config_notes: list[str] | None = None,
        http_client: httpx.Client | None = None,
    ) -> AnalysisResult:
        md = build_report(
            files,
            head_sha=head_sha,
            pr_number=pr_number,
            truncated=truncated,
            config=config,
        )
        return AnalysisResult(markdown=md, findings=[], overall_severity="info")


class RulesAnalyzer:
    def __init__(self, engine: RulesEngine | None = None):
        self.engine = engine or RulesEngine()

    def analyze(
        self,
        files: list[dict[str, Any]],
        *,
        head_sha: str,
        pr_number: int,
        truncated: bool = False,
        config: dict[str, Any] | None = None,
        config_notes: list[str] | None = None,
        http_client: httpx.Client | None = None,
    ) -> AnalysisResult:
        cfg = config or {}
        findings, kept, ignored = self.engine.run(files, cfg)
        md = build_rules_report(
            kept,
            head_sha=head_sha,
            pr_number=pr_number,
            truncated=truncated,
            config=cfg,
            findings=findings,
            ignored_files=ignored,
            config_notes=config_notes,
            llm_result=None,
        )
        overall = max_severity(findings, default="info")
        return AnalysisResult(markdown=md, findings=list(findings), overall_severity=overall)


class RulesLLMAnalyzer:
    """Rules engine + optional OpenAI-compatible LLM review."""

    def __init__(self, engine: RulesEngine | None = None):
        self.engine = engine or RulesEngine()

    def analyze(
        self,
        files: list[dict[str, Any]],
        *,
        head_sha: str,
        pr_number: int,
        truncated: bool = False,
        config: dict[str, Any] | None = None,
        config_notes: list[str] | None = None,
        http_client: httpx.Client | None = None,
    ) -> AnalysisResult:
        cfg = config or {}
        findings, kept, ignored = self.engine.run(files, cfg)
        llm_result = review_with_llm(
            kept,
            rule_findings=findings,
            config=cfg,
            pr_number=pr_number,
            head_sha=head_sha,
            http_client=http_client,
        )
        merged = merge_findings(list(findings) + list(llm_result.findings))
        md = build_rules_report(
            kept,
            head_sha=head_sha,
            pr_number=pr_number,
            truncated=truncated,
            config=cfg,
            findings=merged,
            ignored_files=ignored,
            config_notes=config_notes,
            llm_result=llm_result,
        )
        overall = max_severity(merged, default="info")
        return AnalysisResult(markdown=md, findings=merged, overall_severity=overall)


def get_analyzer(
    config: dict[str, Any] | None = None,
) -> FakeAnalyzer | RulesAnalyzer | RulesLLMAnalyzer:
    mode = (config or {}).get("analyzer", {}).get("mode", "rules+llm")
    if mode == "fake":
        return FakeAnalyzer()
    if mode == "rules":
        return RulesAnalyzer()
    # rules+llm (default) and unknown → RulesLLMAnalyzer (no key → soft skip)
    return RulesLLMAnalyzer()
