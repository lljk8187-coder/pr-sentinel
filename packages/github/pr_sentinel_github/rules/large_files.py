"""Large-files rule — heuristic on additions / patch length / changes."""

from __future__ import annotations

from typing import Any

from .base import Finding


class LargeFilesRule:
    rule_id = "large_files"

    def check(
        self, files: list[dict[str, Any]], config: dict[str, Any]
    ) -> list[Finding]:
        cfg = (config.get("rules") or {}).get("large_files") or {}
        if not cfg.get("enabled", True):
            return []
        max_bytes = int(cfg.get("max_bytes", 1048576))

        findings: list[Finding] = []
        for f in files:
            filename = f.get("filename") or ""
            patch = f.get("patch") or ""
            additions = int(f.get("additions") or 0)
            changes = int(f.get("changes") or 0)
            # Approximate size: prefer patch length; else additions * ~40 bytes;
            # also flag huge change counts.
            approx = len(patch.encode("utf-8")) if patch else additions * 40
            if approx >= max_bytes or changes * 40 >= max_bytes:
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        severity="warning",
                        message=(
                            f"文件可能过大（approx≈{approx} bytes，"
                            f"threshold={max_bytes}；additions={additions}）"
                        ),
                        filename=filename,
                        meta={
                            "approx_bytes": approx,
                            "max_bytes": max_bytes,
                            "additions": additions,
                            "changes": changes,
                        },
                    )
                )
        return findings
