"""Fake analyzer for M1 demo — no LLM."""

from __future__ import annotations

from typing import Any


def build_report(files: list[dict[str, Any]], *, head_sha: str, pr_number: int) -> str:
    """Build a fixed fake quality-gate report from PR file list."""
    names = [f.get("filename", "?") for f in files]
    additions = sum(int(f.get("additions", 0)) for f in files)
    deletions = sum(int(f.get("deletions", 0)) for f in files)
    file_list = "\n".join(f"- `{n}`" for n in names) or "- (no files)"

    return (
        f"## PR Sentinel — M1 假分析报告\n\n"
        f"**PR** #{pr_number} · **SHA** `{head_sha[:12]}`\n\n"
        f"| 指标 | 值 |\n| --- | --- |\n"
        f"| 改动文件数 | {len(files)} |\n"
        f"| +行 | {additions} |\n"
        f"| -行 | {deletions} |\n\n"
        f"### 文件列表\n{file_list}\n\n"
        f"> 这是 M1 骨架的固定假报告，非真实 LLM / 规则引擎结果。\n"
    )


class FakeAnalyzer:
    def analyze(self, files: list[dict[str, Any]], *, head_sha: str, pr_number: int) -> str:
        return build_report(files, head_sha=head_sha, pr_number=pr_number)
