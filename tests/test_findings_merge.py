"""Phase8-M30: cross-source findings merge / dedup."""

from __future__ import annotations

from pr_sentinel_github.findings_merge import merge_findings
from pr_sentinel_github.rules import Finding


def _f(
    *,
    rule_id: str = "r",
    severity: str = "warning",
    message: str = "m",
    filename: str | None = "a.py",
    line: int | None = 10,
    source: str = "rules",
    meta: dict | None = None,
) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=severity,
        message=message,
        filename=filename,
        line=line,
        source=source,
        meta=meta or {},
    )


def test_collision_same_path_line_cross_source_dedups_minus_one():
    a = _f(severity="warning", source="rules", message="rule hit")
    b = _f(severity="error", source="llm", message="llm hit", rule_id="llm.x")
    out = merge_findings([a, b])
    assert len(out) == 1  # 撞车 −1
    assert out[0].severity == "error"
    assert out[0].source == "llm"
    assert out[0].meta.get("sources") == ["rules", "llm"]


def test_different_path_or_line_not_merged():
    a = _f(filename="a.py", line=1, source="rules")
    b = _f(filename="a.py", line=2, source="llm")
    c = _f(filename="b.py", line=1, source="llm")
    out = merge_findings([a, b, c])
    assert len(out) == 3
    assert all("sources" not in f.meta for f in out)


def test_severity_prefers_higher():
    low = _f(severity="info", source="llm", message="soft")
    high = _f(severity="critical", source="rules", message="hard")
    out = merge_findings([low, high])
    assert len(out) == 1
    assert out[0].severity == "critical"
    assert out[0].source == "rules"
    assert out[0].meta.get("sources") == ["llm", "rules"]


def test_same_source_same_key_keeps_one():
    a = _f(severity="warning", source="rules", message="first")
    b = _f(severity="error", source="rules", message="second")
    out = merge_findings([a, b])
    assert len(out) == 1
    assert out[0].severity == "error"
    assert out[0].message == "second"
    assert "sources" not in out[0].meta


def test_empty_and_singleton():
    assert merge_findings([]) == []
    one = _f()
    out = merge_findings([one])
    assert len(out) == 1
    assert out[0].message == one.message
