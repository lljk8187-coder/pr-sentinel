"""GitHub Check Runs + high-severity inline review comments (M8/M11)."""

from __future__ import annotations

import logging
from typing import Any

from .client import GitHubClient
from .rules.base import Finding
from .rules.patch_lines import line_in_patch_right

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


def inline_fingerprint(path: str, line: int, rule_id: str) -> str:
    """HTML comment marker for inline upsert dedup (must include rule_id)."""
    return f"<!-- pr-sentinel:inline:{path}:{line}:{rule_id} -->"


def _patches_by_path(
    files: list[dict[str, Any]] | None = None,
    patches: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build filename → unified-diff patch map from worker PR files or an explicit map."""
    out: dict[str, str] = {}
    if patches:
        for k, v in patches.items():
            if k and v:
                out[str(k)] = str(v)
    for f in files or []:
        if not isinstance(f, dict):
            continue
        name = f.get("filename") or f.get("path")
        patch = f.get("patch")
        if name and patch:
            out[str(name)] = str(patch)
    return out


def _human_inline_body(finding: Finding) -> str:
    body = f"**[{finding.severity}]** {finding.message}"
    if finding.detail:
        body += f"\n\n{finding.detail}"
    return body


def publish_inline_comments(
    client: GitHubClient,
    *,
    owner: str,
    repo: str,
    pr_number: int,
    head_sha: str,
    findings: list[Finding],
    files: list[dict[str, Any]] | None = None,
    patches: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Upsert inline PR review comments for high-severity findings with valid RIGHT lines.

    Uses ``line`` + ``side=RIGHT`` only (never ``position``). Skips invalid / deleted /
    binary / invented lines instead of POSTing (avoids GitHub 422 killing the job).
    Dedup fingerprint: ``<!-- pr-sentinel:inline:{path}:{line}:{rule_id} -->``.
    Same fingerprint on synchronize → PATCH body only (or skip if unchanged).
    """
    patch_map = _patches_by_path(files, patches)
    try:
        existing = client.list_pull_review_comments(owner, repo, pr_number)
    except Exception:
        logger.exception(
            "list_pull_review_comments failed for %s/%s#%s; treating as empty",
            owner,
            repo,
            pr_number,
        )
        existing = []

    by_fp: dict[str, dict[str, Any]] = {}
    for c in existing:
        body = (c.get("body") or "") if isinstance(c, dict) else ""
        if not body.startswith("<!-- pr-sentinel:inline:"):
            continue
        first = body.split("\n", 1)[0].strip()
        by_fp[first] = c

    results: list[dict[str, Any]] = []
    posted = 0
    patched = 0
    skipped = 0

    for f in findings:
        sev = (f.severity or "").lower()
        if sev not in HIGH_SEVERITIES:
            continue
        path = f.path or f.filename
        if not path or f.line is None:
            skipped += 1
            continue
        try:
            line = int(f.line)
        except (TypeError, ValueError):
            skipped += 1
            continue
        if line < 1:
            skipped += 1
            continue

        patch = patch_map.get(path)
        if not patch:
            # Binary / no usable patch / unknown file → skip inline (Check Run OK).
            skipped += 1
            continue
        if not line_in_patch_right(patch, line):
            # Deleted-only / invented line not on RIGHT → never POST.
            skipped += 1
            continue

        rule_id = f.rule_id or "finding"
        fp = inline_fingerprint(path, line, rule_id)
        human = _human_inline_body(f)
        full_body = f"{fp}\n{human}"

        prior = by_fp.get(fp)
        try:
            if prior is not None:
                prior_body = prior.get("body") or ""
                if prior_body == full_body:
                    skipped += 1
                    results.append(prior)
                    continue
                comment_id = int(prior["id"])
                result = client.update_pull_review_comment(
                    owner,
                    repo,
                    comment_id,
                    body=full_body,
                )
                patched += 1
                by_fp[fp] = result
                results.append(result)
            else:
                result = client.create_pull_review_comment(
                    owner,
                    repo,
                    pr_number,
                    body=full_body,
                    commit_id=head_sha,
                    path=path,
                    line=line,
                    side="RIGHT",
                )
                posted += 1
                by_fp[fp] = result
                results.append(result)
        except Exception:
            logger.exception(
                "inline comment failed path=%s line=%s rule=%s; skipping finding",
                path,
                line,
                rule_id,
            )
            skipped += 1
            continue

    logger.info(
        "inline_comments posted=%s patched=%s skipped=%s for %s/%s#%s",
        posted,
        patched,
        skipped,
        owner,
        repo,
        pr_number,
    )
    return results
