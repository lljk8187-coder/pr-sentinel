"""M3: LLM review — skip without key, mock success, redact_secrets."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from common.defaults import get_default_config
from pr_sentinel_github.analyzer import RulesLLMAnalyzer, get_analyzer
from pr_sentinel_github.llm import (
    REDACT_PLACEHOLDER,
    call_chat_completions,
    redact_secrets,
    review_with_llm,
)
from pr_sentinel_github.rules.base import Finding


SAMPLE_FILES = [
    {
        "filename": "src/app.py",
        "additions": 2,
        "deletions": 0,
        "patch": "@@ -0,0 +1,2 @@\n+def hello():\n+    return 1\n",
    }
]


def test_redact_secrets_akia():
    text = "key=AKIAIOSFODNN7EXAMPLE and more"
    out = redact_secrets(text, patterns=[r"AKIA[0-9A-Z]{16}"], enabled=True)
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert REDACT_PLACEHOLDER in out


def test_redact_secrets_disabled():
    text = "key=AKIAIOSFODNN7EXAMPLE"
    out = redact_secrets(text, patterns=[r"AKIA[0-9A-Z]{16}"], enabled=False)
    assert out == text


def test_llm_skipped_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PR_SENTINEL_OPENAI_API_KEY", raising=False)

    cfg = get_default_config()
    cfg["analyzer"]["mode"] = "rules+llm"

    analysis = RulesLLMAnalyzer().analyze(
        SAMPLE_FILES,
        head_sha="deadbeefcafebabe000011112222333344445555",
        pr_number=42,
        truncated=False,
        config=cfg,
        config_notes=[],
    )
    report = analysis.markdown
    assert "llm_skipped" in report
    assert "Assumptions" in report or "assumptions" in report.lower()
    assert "LLM 发现" in report
    assert "规则发现" in report
    assert "severity" in report


def test_llm_success_with_httpx_mock(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

    payload = {
        "findings": [
            {
                "severity": "warning",
                "title": "Missing error handling",
                "detail": "hello() has no try/except",
                "path": "src/app.py",
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/chat/completions")
        body = json.loads(request.content.decode())
        # prompt should not contain unredacted typical secrets if present
        assert body["model"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(payload)}}
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)

    cfg = get_default_config()
    cfg["analyzer"]["mode"] = "rules+llm"
    # Include a secret in patch to exercise redact path
    files = [
        {
            "filename": "src/app.py",
            "additions": 1,
            "deletions": 0,
            "patch": "+TOKEN=AKIAIOSFODNN7EXAMPLE\n+def hello():\n+    return 1\n",
        }
    ]

    analysis = RulesLLMAnalyzer().analyze(
        files,
        head_sha="deadbeefcafebabe000011112222333344445555",
        pr_number=42,
        truncated=True,
        config=cfg,
        http_client=client,
    )
    report = analysis.markdown
    assert "Missing error handling" in report
    assert "LLM 发现" in report
    assert "Limits 截断" in report
    assert "warning" in report
    # Overall severity should reflect LLM warning at least
    assert "**severity**" in report


def test_call_chat_completions_5xx_raises_transient():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    from pr_sentinel_github.llm import LLMTransientError

    with pytest.raises(LLMTransientError):
        call_chat_completions(
            api_key="sk-x",
            messages=[{"role": "user", "content": "hi"}],
            http_client=client,
        )


def test_get_analyzer_modes():
    assert type(get_analyzer({"analyzer": {"mode": "fake"}})).__name__ == "FakeAnalyzer"
    assert type(get_analyzer({"analyzer": {"mode": "rules"}})).__name__ == "RulesAnalyzer"
    assert type(get_analyzer({"analyzer": {"mode": "rules+llm"}})).__name__ == "RulesLLMAnalyzer"
    assert type(get_analyzer(None)).__name__ == "RulesLLMAnalyzer"


def test_review_with_llm_client_error_soft_skips(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-bad")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = review_with_llm(
        SAMPLE_FILES,
        rule_findings=[],
        config=get_default_config(),
        pr_number=1,
        head_sha="abc",
        http_client=client,
    )
    assert result.skipped is True
    assert any("llm_skipped" in a for a in result.assumptions)


def test_finding_source_fields():
    f = Finding(
        rule_id="llm",
        severity="high",
        message="Title here",
        filename="a.py",
        source="llm",
        detail="more",
    )
    assert f.title == "Title here"
    assert f.path == "a.py"
    assert f.to_dict()["source"] == "llm"


def test_worker_settings_retries():
    """arq WorkerSettings exposes max_tries / job_timeout for M3."""
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    path = root / "apps" / "worker" / "main.py"
    spec = importlib.util.spec_from_file_location("pr_sentinel_worker_main", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    assert mod.WorkerSettings.max_tries == 3
    assert mod.WorkerSettings.job_timeout == 300
    assert mod.WorkerSettings.retry_jobs is True
