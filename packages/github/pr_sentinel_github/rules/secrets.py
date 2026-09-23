"""Secrets rule — regex scan over filename + patch."""

from __future__ import annotations

import re
from typing import Any

from .base import Finding


class SecretsRule:
    rule_id = "secrets"

    def check(
        self, files: list[dict[str, Any]], config: dict[str, Any]
    ) -> list[Finding]:
        cfg = (config.get("rules") or {}).get("secrets") or {}
        if not cfg.get("enabled", True):
            return []
        patterns = list(cfg.get("patterns") or [])
        compiled: list[re.Pattern[str]] = []
        for p in patterns:
            try:
                compiled.append(re.compile(p))
            except re.error:
                continue

        findings: list[Finding] = []
        for f in files:
            filename = f.get("filename") or ""
            patch = f.get("patch") or ""
            haystack = f"{filename}\n{patch}"
            for rx in compiled:
                for m in rx.finditer(haystack):
                    findings.append(
                        Finding(
                            rule_id=self.rule_id,
                            severity="error",
                            message=f"疑似密钥匹配 `{rx.pattern}`",
                            filename=filename,
                            meta={"match": m.group(0)[:80], "pattern": rx.pattern},
                        )
                    )
                    break  # one finding per pattern per file
        return findings
