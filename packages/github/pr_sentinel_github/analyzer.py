"""Fake analyzer for M1 demo — no LLM. Uses built-in default config constants."""

from __future__ import annotations

from typing import Any


def build_report(
    files: list[dict[str, Any]],
    *,
    head_sha: str,
    pr_number: int,
    truncated: bool = False,
    config: dict[str, Any] | None = None,
) -> str:
    """Build a fixed fake quality-gate report from PR file list."""
    names = [f.get("filename", "?") for f in files]
    additions = sum(int(f.get("additions", 0)) for f in files)
    deletions = sum(int(f.get("deletions", 0)) for f in files)
    file_list = "\n".join(f"- `{n}`" for n in names[:50]) or "- (no files)"
    if len(names) > 50:
        file_list += f"\n- … 另有 {len(names) - 50} 个文件未列出"

    trunc_note = ""
    if truncated:
        trunc_note = "\n\n> ⚠️ Diff 已按 `max_pages` / `max_files` 截断。\n"

    mode = (config or {}).get("analyzer", {}).get("mode", "fake")

    return (
        f"## PR Sentinel — M1 假分析报告\n\n"
        f"**PR** #{pr_number} · **SHA** `{head_sha[:12]}` · **mode** `{mode}`\n\n"
        f"| 指标 | 值 |\n| --- | --- |\n"
        f"| 改动文件数 | {len(files)} |\n"
        f"| +行 | {additions} |\n"
        f"| -行 | {deletions} |\n"
        f"| 截断 | {'是' if truncated else '否'} |\n\n"
        f"### 文件列表\n{file_list}\n"
        f"{trunc_note}\n"
        f"> 这是 M1 骨架的固定假报告（内置默认配置，未读仓库 `.pr-sentinel.yml`）。\n"
    )


class FakeAnalyzer:
    def analyze(
        self,
        files: list[dict[str, Any]],
        *,
        head_sha: str,
        pr_number: int,
        truncated: bool = False,
        config: dict[str, Any] | None = None,
    ) -> str:
        return build_report(
            files,
            head_sha=head_sha,
            pr_number=pr_number,
            truncated=truncated,
            config=config,
        )
