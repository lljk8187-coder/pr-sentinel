"""Large-files rule — heuristic on patch bytes / additions / binary hints."""

from __future__ import annotations

from typing import Any

from .base import Finding

_DEFAULT_BINARY_EXTENSIONS = [
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".pdf",
    ".zip",
    ".gz",
    ".whl",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
]


def _has_binary_extension(filename: str, extensions: list[str]) -> bool:
    lower = filename.lower()
    for ext in extensions:
        e = ext.lower()
        if not e.startswith("."):
            e = "." + e
        if lower.endswith(e):
            return True
    return False


class LargeFilesRule:
    rule_id = "large_files"

    def check(
        self, files: list[dict[str, Any]], config: dict[str, Any]
    ) -> list[Finding]:
        cfg = (config.get("rules") or {}).get("large_files") or {}
        if not cfg.get("enabled", True):
            return []
        max_bytes = int(cfg.get("max_bytes", 1048576))
        max_additions = int(cfg.get("max_additions", 2000))
        binary_extensions = list(
            cfg.get("binary_extensions") or _DEFAULT_BINARY_EXTENSIONS
        )

        findings: list[Finding] = []
        for f in files:
            filename = f.get("filename") or ""
            # GitHub omits / nulls patch for binary or truncated diffs.
            raw_patch = f.get("patch")
            has_patch = raw_patch is not None and raw_patch != ""
            patch = raw_patch if isinstance(raw_patch, str) else ""
            additions = int(f.get("additions") or 0)
            changes = int(f.get("changes") or 0)
            approx_patch_bytes = len(patch.encode("utf-8")) if has_patch else 0
            is_bin_ext = _has_binary_extension(filename, binary_extensions)

            reasons: list[str] = []
            binary_or_truncated = False

            if has_patch and approx_patch_bytes >= max_bytes:
                reasons.append("patch_too_large")
            if additions >= max_additions:
                reasons.append("additions_too_high")
            # No Contents API / no invented file size — only PR file metadata.
            if not has_patch and (is_bin_ext or changes >= max_additions):
                binary_or_truncated = True
                reasons.append("binary_or_truncated")

            if not reasons:
                continue

            reason = "+".join(reasons)
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    severity="warning",
                    message=(
                        f"文件可能过大（reason={reason}；"
                        f"approx_patch_bytes={approx_patch_bytes}；"
                        f"additions={additions}；"
                        f"binary_or_truncated={binary_or_truncated}）"
                    ),
                    filename=filename,
                    meta={
                        "reason": reason,
                        "approx_patch_bytes": approx_patch_bytes,
                        "additions": additions,
                        "changes": changes,
                        "max_bytes": max_bytes,
                        "max_additions": max_additions,
                        "binary_or_truncated": binary_or_truncated,
                    },
                )
            )
        return findings
