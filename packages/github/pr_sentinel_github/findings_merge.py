"""Cross-source finding merge / dedup (Phase8-M30).

Merge key: ``(path, line)`` i.e. ``(filename, line)``.
Same key across sources keeps the higher-severity finding and records
``meta.sources``. Same source + same key keeps a single entry (higher severity).
"""

from __future__ import annotations

from dataclasses import replace

from .rules import Finding


def _severity_rank(sev: str) -> int:
    order = {
        "info": 1,
        "low": 1,
        "warning": 2,
        "medium": 2,
        "error": 3,
        "high": 3,
        "critical": 4,
    }
    return order.get((sev or "info").lower(), 1)


def _merge_key(item: Finding) -> tuple[str | None, int | None]:
    return (item.filename, item.line)


def merge_findings(findings: list[Finding]) -> list[Finding]:
    """Dedup findings by path+line; cross-source collisions keep higher severity."""
    if not findings:
        return []

    buckets: dict[tuple[str | None, int | None], list[Finding]] = {}
    order: list[tuple[str | None, int | None]] = []
    for item in findings:
        key = _merge_key(item)
        if key not in buckets:
            order.append(key)
            buckets[key] = []
        buckets[key].append(item)

    out: list[Finding] = []
    for key in order:
        group = buckets[key]
        # Per-source: keep one (higher severity; first on tie)
        by_source: dict[str, Finding] = {}
        source_order: list[str] = []
        for item in group:
            src = item.source or "rules"
            if src not in by_source:
                source_order.append(src)
                by_source[src] = item
            elif _severity_rank(item.severity) > _severity_rank(by_source[src].severity):
                by_source[src] = item

        best = by_source[source_order[0]]
        for src in source_order[1:]:
            cand = by_source[src]
            if _severity_rank(cand.severity) > _severity_rank(best.severity):
                best = cand

        new_meta = dict(best.meta or {})
        if len(source_order) > 1:
            new_meta["sources"] = list(source_order)
        out.append(replace(best, meta=new_meta))

    return out
