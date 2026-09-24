"""Phase8-M31: sticky body clamp, report severity order, inline detail truncate."""

from __future__ import annotations

from pathlib import Path

from pr_sentinel_github.analyzer import build_rules_report
from pr_sentinel_github.check_runs import _INLINE_DETAIL_MAX, _human_inline_body
from pr_sentinel_github.comments import (
    STICKY_BODY_MAX,
    STICKY_TRUNCATION_MARK,
    clamp_sticky_body,
    summary_marker,
    upsert_pr_comment,
)
from pr_sentinel_github.rules import Finding


def test_clamp_sticky_short_unchanged():
    marker = summary_marker("acme", "demo", 1)
    body, trunc = clamp_sticky_body(marker, "hello report")
    assert trunc is False
    assert body == f"{marker}\nhello report"
    assert STICKY_TRUNCATION_MARK not in body


def test_clamp_sticky_over_limit_truncates_and_marks():
    marker = summary_marker("acme", "demo", 1)
    huge = "X" * (STICKY_BODY_MAX + 5000)
    body, trunc = clamp_sticky_body(marker, huge)
    assert trunc is True
    assert len(body) <= STICKY_BODY_MAX
    assert body.startswith(marker)
    assert STICKY_TRUNCATION_MARK in body
    assert "报告已截断" in body


def test_upsert_applies_sticky_clamp(tmp_path: Path):
    (tmp_path / "issue_comments.json").write_text("[]")
    from pr_sentinel_github.client import GitHubClient

    client = GitHubClient(use_fixtures=True, fixtures_dir=tmp_path)
    huge = "Y" * (STICKY_BODY_MAX + 8000)
    result = upsert_pr_comment(
        client,
        owner="acme",
        repo="demo",
        pr_number=7,
        head_sha="a" * 40,
        report_body=huge,
    )
    assert result["_action"] == "create"
    posts = [c for c in client.calls if c["method"] == "POST"]
    assert len(posts) == 1
    posted = posts[0]["body"]
    assert len(posted) <= STICKY_BODY_MAX
    assert STICKY_TRUNCATION_MARK in posted
    assert summary_marker("acme", "demo", 7) in posted


def test_report_findings_sorted_by_severity():
    findings = [
        Finding(
            rule_id="secrets",
            severity="info",
            message="soft",
            filename="a.py",
            source="rules",
        ),
        Finding(
            rule_id="secrets",
            severity="error",
            message="hard",
            filename="a.py",
            source="rules",
        ),
        Finding(
            rule_id="secrets",
            severity="warning",
            message="mid",
            filename="a.py",
            source="rules",
        ),
        Finding(
            rule_id="llm.x",
            severity="low",
            message="llm-low",
            filename="b.py",
            source="llm",
        ),
        Finding(
            rule_id="llm.x",
            severity="high",
            message="llm-high",
            filename="b.py",
            source="llm",
        ),
    ]
    md = build_rules_report(
        [],
        head_sha="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        pr_number=1,
        config={"analyzer": {"mode": "rules+llm"}},
        findings=findings,
    )
    # Within secrets rule block: error before warning before info
    secrets_block = md.split("#### `secrets`")[1].split("### LLM")[0]
    assert secrets_block.index("**error**") < secrets_block.index("**warning**")
    assert secrets_block.index("**warning**") < secrets_block.index("**info**")
    llm_block = md.split("### LLM 发现")[1]
    assert llm_block.index("**high**") < llm_block.index("**low**")


def test_inline_detail_truncated_at_2k():
    f = Finding(
        rule_id="r",
        severity="error",
        message="hit",
        filename="a.py",
        line=3,
        detail="D" * (_INLINE_DETAIL_MAX + 400),
        source="rules",
    )
    body = _human_inline_body(f)
    assert "detail truncated" in body
    # detail portion capped; full original must not appear
    assert "D" * (_INLINE_DETAIL_MAX + 400) not in body
    assert body.count("D") == _INLINE_DETAIL_MAX


def test_inline_detail_short_unchanged():
    f = Finding(
        rule_id="r",
        severity="error",
        message="hit",
        detail="short detail",
        source="rules",
    )
    assert _human_inline_body(f) == "**[error]** hit\n\nshort detail"
