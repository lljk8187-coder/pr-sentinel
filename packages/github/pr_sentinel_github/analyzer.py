"""Analyzers: FakeAnalyzer (M1) + RulesAnalyzer (M2 rules engine)."""

from __future__ import annotations

from typing import Any

from .rules import Finding, RulesEngine


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


def _severity_emoji(severity: str) -> str:
    return {"error": "🛑", "warning": "⚠️", "info": "ℹ️"}.get(severity, "•")


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
) -> str:
    """Markdown report with findings + limits truncation notice."""
    cfg = config or {}
    mode = cfg.get("analyzer", {}).get("mode", "rules")
    findings = findings or []
    ignored_files = ignored_files or []
    config_notes = config_notes or []

    additions = sum(int(f.get("additions", 0)) for f in files)
    deletions = sum(int(f.get("deletions", 0)) for f in files)

    lines: list[str] = [
        "## PR Sentinel — 规则引擎报告",
        "",
        f"**PR** #{pr_number} · **SHA** `{head_sha[:12]}` · **mode** `{mode}`",
        "",
        "| 指标 | 值 |",
        "| --- | --- |",
        f"| 分析文件数 | {len(files)} |",
        f"| 忽略文件数 | {len(ignored_files)} |",
        f"| Findings | {len(findings)} |",
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
            "`diff.max_files`（或环境变量）截断，后续规则仅基于已拉取文件，报告可能不完整。"
        )
        lines.append("")

    lines.append("### Findings")
    if not findings:
        lines.append("无发现问题。")
    else:
        by_rule: dict[str, list[Finding]] = {}
        for fnd in findings:
            by_rule.setdefault(fnd.rule_id, []).append(fnd)
        for rule_id, items in by_rule.items():
            lines.append(f"#### `{rule_id}` ({len(items)})")
            for item in items:
                loc = f"`{item.filename}` — " if item.filename else ""
                lines.append(
                    f"- {_severity_emoji(item.severity)} **{item.severity}** "
                    f"{loc}{item.message}"
                )
            lines.append("")

    if ignored_files:
        names = [f.get("filename", "?") for f in ignored_files[:30]]
        lines.append("### 已忽略路径")
        for n in names:
            lines.append(f"- `{n}`")
        if len(ignored_files) > 30:
            lines.append(f"- … 另有 {len(ignored_files) - 30} 个")
        lines.append("")

    lines.append("> RulesAnalyzer（无 LLM）。配置来自 default branch `.pr-sentinel.yml` 与 DEFAULT_CONFIG 深度合并。")
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
    ) -> str:
        return build_report(
            files,
            head_sha=head_sha,
            pr_number=pr_number,
            truncated=truncated,
            config=config,
        )


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
    ) -> str:
        cfg = config or {}
        findings, kept, ignored = self.engine.run(files, cfg)
        return build_rules_report(
            kept,
            head_sha=head_sha,
            pr_number=pr_number,
            truncated=truncated,
            config=cfg,
            findings=findings,
            ignored_files=ignored,
            config_notes=config_notes,
        )


def get_analyzer(config: dict[str, Any] | None = None) -> FakeAnalyzer | RulesAnalyzer:
    mode = (config or {}).get("analyzer", {}).get("mode", "rules")
    if mode == "fake":
        return FakeAnalyzer()
    return RulesAnalyzer()
