"""GitHub Check Runs + high-severity inline review comments (M8)."""

from __future__ import annotations

import logging
from typing import Any

from .client import GitHubClient
from .rules.base import Finding

logger = logging.getLogger(__name__)

CHECK_RUN_NAME = "pr-sentinel"
MAX_ANNOTATIONS = 50
HIGH_SEVERITIES = frozenset({"error", "high", "critical"})
_OUTPUT_TEXT_LIMIT = 65535


def conclusion_for_findings(findings: list[Finding]) -> str:
    """``success`` unless any finding has severity in {error, high, critical}."""
    for f in findings:
        if (f.severity or "").lower() in HIGH_SEVERITIES:
            return "failure"
    return "success"


def annotation_level(severity: str) -> str:
    s = (severity or "").lower()
    if s in HIGH_SEVERITIES:
        return "failure"
    if s in {"warning", "medium"}:
        return "warning"
    return "notice"


def findings_to_annotations(
    findings: list[Finding],
    *,
    limit: int = MAX_ANNOTATIONS,
) -> tuple[list[dict[str, Any]], int]:
    """Map findings with path+line to Check Run annotations.

    Returns ``(annotations, truncated_count)`` for eligible findings omitted
    past the per-request limit (50).
    """
    annotations: list[dict[str, Any]] = []
    truncated = 0
    for f in findings:
        path = f.path or f.filename
        if not path or f.line is None:
            continue
        try:
            line = int(f.line)
        except (TypeError, ValueError):
            continue
        if line < 1:
            continue
        if len(annotations) >= limit:
            truncated += 1
            continue
        title = (f.rule_id or "finding")[:255]
        message = f.message or ""
        if f.detail:
            message = f"{message}\n{f.detail}" if message else f.detail
        annotations.append(
            {
                "path": path,
                "start_line": line,
                "end_line": line,
                "annotation_level": annotation_level(f.severity),
                "message": message[:65535],
                "title": title,
            }
        )
    return annotations, truncated


def build_check_output_summary(
    report_md: str,
    findings: list[Finding],
    truncated_annos: int,
) -> str:
    """Short summary for Check Run output (may truncate long report bodies)."""
    conclusion = conclusion_for_findings(findings)
    n = len(findings)
    high = sum(1 for f in findings if (f.severity or "").lower() in HIGH_SEVERITIES)
    lines = [
        f"**Conclusion:** `{conclusion}` · **findings:** {n} · **high+:** {high}",
        "",
    ]
    if truncated_annos:
        lines.append(
            f"> ⚠️ Annotations truncated: {truncated_annos} additional "
            f"path+line finding(s) omitted (GitHub limit {MAX_ANNOTATIONS} per request)."
        )
        lines.append("")
    body = (report_md or "").strip()
    if body:
        budget = _OUTPUT_TEXT_LIMIT - sum(len(x) + 1 for x in lines) - 80
        if budget < 200:
            budget = 200
        if len(body) > budget:
            body = body[: budget - 20] + "\n\n… (truncated)"
        lines.append(body)
    summary = "\n".join(lines)
    if len(summary) > _OUTPUT_TEXT_LIMIT:
        summary = summary[: _OUTPUT_TEXT_LIMIT - 20] + "\n\n… (truncated)"
    return summary


def publish_check_run(
    client: GitHubClient,
    *,
    owner: str,
    repo: str,
    head_sha: str,
    findings: list[Finding],
    report_body: str,
    name: str = CHECK_RUN_NAME,
) -> dict[str, Any]:
    """Create ``in_progress`` Check Run, then complete with annotations + conclusion."""
    created = client.create_check_run(
        owner,
        repo,
        name=name,
        head_sha=head_sha,
        status="in_progress",
    )
    check_run_id = int(created["id"])
    annotations, truncated = findings_to_annotations(findings)
    conclusion = conclusion_for_findings(findings)
    summary = build_check_output_summary(report_body, findings, truncated)
    title = f"PR Sentinel — {conclusion}"
    output: dict[str, Any] = {
        "title": title[:255],
        "summary": summary,
        "annotations": annotations,
    }
    if report_body:
        text = report_body
        if len(text) > _OUTPUT_TEXT_LIMIT:
            text = text[: _OUTPUT_TEXT_LIMIT - 20] + "\n\n… (truncated)"
        output["text"] = text

    updated = client.update_check_run(
        owner,
        repo,
        check_run_id,
        status="completed",
        conclusion=conclusion,
        output=output,
    )
    updated.setdefault("id", check_run_id)
    updated["_conclusion"] = conclusion
    updated["_annotations"] = len(annotations)
    updated["_truncated_annotations"] = truncated
    logger.info(
        "check_run %s conclusion=%s annotations=%s truncated=%s sha=%s",
        check_run_id,
        conclusion,
        len(annotations),
        truncated,
        head_sha[:12],
    )
    return updated


def publish_inline_comments(
    client: GitHubClient,
    *,
    owner: str,
    repo: str,
    pr_number: int,
    head_sha: str,
    findings: list[Finding],
) -> list[dict[str, Any]]:
    """Post inline PR review comments for high-severity findings with path+line.

    Findings without a line are skipped (Check Run / sticky only — never invent lines).
    """
    results: list[dict[str, Any]] = []
    for f in findings:
        sev = (f.severity or "").lower()
        if sev not in HIGH_SEVERITIES:
            continue
        path = f.path or f.filename
        if not path or f.line is None:
            continue
        try:
            line = int(f.line)
        except (TypeError, ValueError):
            continue
        if line < 1:
            continue
        body = f"**[{f.severity}]** {f.message}"
        if f.detail:
            body += f"\n\n{f.detail}"
        result = client.create_pull_review_comment(
            owner,
            repo,
            pr_number,
            body=body,
            commit_id=head_sha,
            path=path,
            line=line,
            side="RIGHT",
        )
        results.append(result)
    logger.info(
        "inline_comments posted=%s for %s/%s#%s",
        len(results),
        owner,
        repo,
        pr_number,
    )
    return results
