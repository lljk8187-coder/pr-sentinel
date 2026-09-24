"""OpenAI-compatible LLM review via httpx (no hard openai SDK dependency)."""

from __future__ import annotations

import copy
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from .rules.base import Finding

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
REDACT_PLACEHOLDER = "***REDACTED***"

# Built-in patterns used when config has none (also used for privacy redact).
_DEFAULT_SECRET_PATTERNS = [
    r"AKIA[0-9A-Z]{16}",
    r"-----BEGIN (RSA |OPENSSH )?PRIVATE KEY-----",
    r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[^\s'\"]{8,}",
    r"ghp_[A-Za-z0-9]{36}",
    r"sk-[A-Za-z0-9]{20,}",
]


class LLMTransientError(Exception):
    """Network / 5xx / timeout — should bubble for arq retry."""


class LLMClientError(Exception):
    """Auth / 4xx (non-429) — soft-skip LLM, do not retry forever."""


@dataclass
class LLMReviewResult:
    findings: list[Finding] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str | None = None
    assumptions: list[str] = field(default_factory=list)
    raw_content: str | None = None


def get_openai_api_key() -> str | None:
    key = (
        os.environ.get("PR_SENTINEL_OPENAI_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()
    return key or None


def get_openai_base_url() -> str:
    return (
        os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("PR_SENTINEL_OPENAI_BASE_URL")
        or DEFAULT_BASE_URL
    ).rstrip("/")


def get_openai_model() -> str:
    return (
        os.environ.get("OPENAI_MODEL")
        or os.environ.get("PR_SENTINEL_OPENAI_MODEL")
        or DEFAULT_MODEL
    )


def _compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    out: list[re.Pattern[str]] = []
    for p in patterns:
        try:
            out.append(re.compile(p))
        except re.error:
            continue
    return out


def redact_secrets(
    text: str,
    *,
    patterns: list[str] | None = None,
    enabled: bool = True,
) -> str:
    """Replace secret-like substrings before sending text to an LLM."""
    if not enabled or not text:
        return text
    pats = patterns if patterns is not None else list(_DEFAULT_SECRET_PATTERNS)
    compiled = _compile_patterns(pats)
    redacted = text
    for rx in compiled:
        redacted = rx.sub(REDACT_PLACEHOLDER, redacted)
    return redacted


def _secret_patterns_from_config(config: dict[str, Any]) -> list[str]:
    rules = (config.get("rules") or {}).get("secrets") or {}
    pats = list(rules.get("patterns") or [])
    # Always include a few extras for redact safety
    for extra in _DEFAULT_SECRET_PATTERNS:
        if extra not in pats:
            pats.append(extra)
    return pats


def _redact_any(value: Any, *, patterns: list[str], enabled: bool) -> Any:
    """Recursively redact string leaves (and nested dict/list values)."""
    if isinstance(value, str):
        return redact_secrets(value, patterns=patterns, enabled=enabled)
    if isinstance(value, dict):
        return {
            k: _redact_any(v, patterns=patterns, enabled=enabled)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact_any(v, patterns=patterns, enabled=enabled) for v in value]
    return value


def redact_findings_for_storage(
    findings: list[dict[str, Any]],
    report_md: str | None,
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None]:
    """Redact secret-like strings in findings + report (M12 storage / M14 outbound).

    Respects ``privacy.redact_secrets`` (default True). Operates on a deep copy.
    Worker uses the same redacted result for GitHub publish and Postgres writeback.
    """
    privacy = config.get("privacy") or {}
    enabled = bool(privacy.get("redact_secrets", True))
    if not enabled:
        return copy.deepcopy(findings), report_md

    patterns = _secret_patterns_from_config(config)
    out: list[dict[str, Any]] = []
    for item in findings:
        fd = copy.deepcopy(item) if isinstance(item, dict) else item
        if not isinstance(fd, dict):
            out.append(fd)
            continue
        for key in ("message", "detail", "title"):
            if key in fd and isinstance(fd[key], str):
                fd[key] = redact_secrets(fd[key], patterns=patterns, enabled=True)
        if "meta" in fd and fd["meta"] is not None:
            fd["meta"] = _redact_any(fd["meta"], patterns=patterns, enabled=True)
        out.append(fd)

    redacted_report = report_md
    if isinstance(report_md, str):
        redacted_report = redact_secrets(report_md, patterns=patterns, enabled=True)
    return out, redacted_report


def truncate_patch_text(files: list[dict[str, Any]], max_chars: int) -> tuple[str, bool]:
    """Build a concatenated patch string, truncated to *max_chars*."""
    parts: list[str] = []
    total = 0
    truncated = False
    for f in files:
        filename = f.get("filename") or "?"
        patch = f.get("patch") or ""
        block = f"--- {filename}\n{patch}\n"
        if total + len(block) > max_chars:
            remain = max_chars - total
            if remain > 0:
                parts.append(block[:remain])
            truncated = True
            break
        parts.append(block)
        total += len(block)
    return "".join(parts), truncated


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


def max_severity(findings: list[Finding], default: str = "info") -> str:
    if not findings:
        return default
    best = max(findings, key=lambda f: _severity_rank(f.severity))
    return best.severity


def _parse_llm_findings(content: str) -> tuple[list[Finding], bool]:
    """Parse model JSON (or fenced JSON) into Finding list.

    Returns ``(findings, soft)`` where *soft* is True when the content could not
    be parsed as JSON (caller should soft-skip without synthesizing a Finding).
    """
    text = content.strip()
    if text.startswith("```"):
        # strip markdown fence
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    data: Any
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find a JSON object/array in the text
        m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
        if not m:
            return [], True
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return [], True

    items: list[Any]
    if isinstance(data, dict):
        items = data.get("findings") or data.get("issues") or []
        if not items and ("severity" in data or "title" in data or "message" in data):
            items = [data]
    elif isinstance(data, list):
        items = data
    else:
        items = []

    findings: list[Finding] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "info").lower()
        title = str(item.get("title") or item.get("message") or "LLM finding")
        detail = str(item.get("detail") or item.get("description") or "")
        path = item.get("path") or item.get("filename")
        line_val: int | None = None
        raw_line = item.get("line")
        if raw_line is not None and raw_line != "":
            try:
                line_val = int(raw_line)
            except (TypeError, ValueError):
                line_val = None
            if line_val is not None and line_val < 1:
                line_val = None
        findings.append(
            Finding(
                rule_id="llm",
                severity=severity if severity in {
                    "info", "warning", "error", "low", "medium", "high", "critical"
                } else "info",
                message=title,
                filename=str(path) if path else None,
                source="llm",
                detail=detail,
                line=line_val,
                meta={k: v for k, v in item.items() if k not in {
                    "severity", "title", "message", "detail", "description",
                    "path", "filename", "line",
                }},
            )
        )
    return findings, False


def build_llm_prompt(
    *,
    files: list[dict[str, Any]],
    rule_findings: list[Finding],
    patch_text: str,
    pr_number: int,
    head_sha: str,
) -> list[dict[str, str]]:
    file_list = "\n".join(
        f"- {f.get('filename', '?')} (+{f.get('additions', 0)}/-{f.get('deletions', 0)})"
        for f in files[:80]
    ) or "- (no files)"
    rules_summary = "\n".join(
        f"- [{f.severity}] {f.filename or ''}: {f.message}" for f in rule_findings[:40]
    ) or "- (none)"

    system = (
        "You are PR Sentinel, a careful code-review assistant. "
        "Review the pull request diff for bugs, security, and test quality. "
        "Respond ONLY with JSON of the form: "
        '{"findings":[{"severity":"info|warning|error|low|medium|high|critical",'
        '"title":"...","detail":"...","path":"optional/file"}]}. '
        "If nothing notable, return {\"findings\":[]}."
    )
    user = (
        f"PR #{pr_number} head `{head_sha[:12]}`\n\n"
        f"## Changed files\n{file_list}\n\n"
        f"## Rule engine findings\n{rules_summary}\n\n"
        f"## Patch (may be truncated / secrets redacted)\n```\n{patch_text}\n```\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def call_chat_completions(
    *,
    api_key: str,
    messages: list[dict[str, str]],
    model: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.2,
    timeout: float = 60.0,
    http_client: httpx.Client | None = None,
) -> str:
    """POST /v1/chat/completions; return assistant message content.

    Raises LLMTransientError on timeout / network / 5xx / 429.
    Raises LLMClientError on other 4xx.
    """
    url = f"{(base_url or get_openai_base_url()).rstrip('/')}/chat/completions"
    payload = {
        "model": model or get_openai_model(),
        "temperature": temperature,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    owns = http_client is None
    client = http_client or httpx.Client(timeout=timeout)
    try:
        try:
            resp = client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMTransientError(f"LLM timeout: {exc}") from exc
        except httpx.TransportError as exc:
            raise LLMTransientError(f"LLM network error: {exc}") from exc

        if resp.status_code >= 500 or resp.status_code == 429:
            raise LLMTransientError(
                f"LLM HTTP {resp.status_code}: {resp.text[:300]}"
            )
        if resp.status_code >= 400:
            raise LLMClientError(
                f"LLM HTTP {resp.status_code}: {resp.text[:300]}"
            )

        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMClientError(f"unexpected LLM response shape: {data!r}") from exc
    finally:
        if owns:
            client.close()


def review_with_llm(
    files: list[dict[str, Any]],
    *,
    rule_findings: list[Finding],
    config: dict[str, Any],
    pr_number: int,
    head_sha: str,
    http_client: httpx.Client | None = None,
    api_key: str | None = None,
) -> LLMReviewResult:
    """Run LLM review or soft-skip when disabled / no key / client error."""
    llm_cfg = config.get("llm") or {}
    privacy = config.get("privacy") or {}
    redact = bool(privacy.get("redact_secrets", True))
    enabled = bool(llm_cfg.get("enabled", True))
    max_chars = int(llm_cfg.get("max_patch_chars") or 12000)
    temperature = float(llm_cfg.get("temperature") if llm_cfg.get("temperature") is not None else 0.2)

    result = LLMReviewResult()

    if not enabled:
        result.skipped = True
        result.skip_reason = "llm.enabled=false"
        result.assumptions.append("llm_skipped: true — llm.enabled=false")
        return result

    key = api_key if api_key is not None else get_openai_api_key()
    if not key:
        result.skipped = True
        result.skip_reason = "missing OPENAI_API_KEY / PR_SENTINEL_OPENAI_API_KEY"
        result.assumptions.append(
            "llm_skipped: true — 未配置 OPENAI_API_KEY 或 PR_SENTINEL_OPENAI_API_KEY，已降级为仅规则引擎。"
        )
        return result

    patch_text, patch_truncated = truncate_patch_text(files, max_chars)
    if redact:
        patterns = _secret_patterns_from_config(config)
        patch_text = redact_secrets(patch_text, patterns=patterns, enabled=True)

    if patch_truncated:
        result.assumptions.append(
            f"LLM patch 已按 llm.max_patch_chars={max_chars} 截断。"
        )

    messages = build_llm_prompt(
        files=files,
        rule_findings=rule_findings,
        patch_text=patch_text,
        pr_number=pr_number,
        head_sha=head_sha,
    )
    # Also redact the full prompt user content for safety (file names rarely secret)
    if redact:
        patterns = _secret_patterns_from_config(config)
        for msg in messages:
            if msg.get("role") == "user":
                msg["content"] = redact_secrets(
                    msg["content"], patterns=patterns, enabled=True
                )

    try:
        content = call_chat_completions(
            api_key=key,
            messages=messages,
            temperature=temperature,
            http_client=http_client,
        )
    except LLMClientError as exc:
        logger.warning("LLM client error (soft-skip): %s", exc)
        result.skipped = True
        result.skip_reason = str(exc)
        result.assumptions.append(f"llm_skipped: true — {exc}")
        return result
    # LLMTransientError intentionally propagates for arq retry

    result.raw_content = content
    findings, parse_soft = _parse_llm_findings(content)
    if parse_soft:
        logger.warning(
            "LLM parse soft-skip (non-JSON or unparseable content): %s",
            (content or "")[:300],
        )
        result.findings = []
        result.assumptions.append(
            "llm_parse_soft: true — LLM 返回无法解析为结构化 findings 的内容，已降级忽略本次 LLM 结果。"
        )
        return result
    result.findings = findings
    return result
