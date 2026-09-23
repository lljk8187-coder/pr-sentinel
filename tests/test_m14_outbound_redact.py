"""M14: outbound GitHub publish uses redacted findings/report (before Check Run/sticky/inline)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from common.defaults import get_default_config
from pr_sentinel_github.llm import REDACT_PLACEHOLDER
from pr_sentinel_github.rules.base import Finding


AKIA = "AKIAIOSFODNN7EXAMPLE"
ROOT = Path(__file__).resolve().parents[1]


def _load_worker_main():
    path = ROOT / "apps" / "worker" / "main.py"
    spec = importlib.util.spec_from_file_location("pr_sentinel_worker_main_m14", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    for pth in (ROOT, ROOT / "packages", ROOT / "packages" / "github"):
        sp = str(pth)
        if sp not in sys.path:
            sys.path.insert(0, sp)
    spec.loader.exec_module(mod)
    return mod


def _fake_analysis():
    class _FakeAnalysis:
        markdown = f"# PR Sentinel\n\nAWS key {AKIA} leaked\n"
        findings = [
            Finding(
                rule_id="secrets",
                severity="error",
                message=f"疑似密钥 {AKIA}",
                filename="leak.env",
                detail=f"detail {AKIA}",
                line=3,
                meta={"match": AKIA, "pattern": "AKIA"},
            )
        ]

    class _FakeAnalyzer:
        def analyze(self, *args, **kwargs):
            return _FakeAnalysis()

    return _FakeAnalyzer()


def _run_process_job(monkeypatch, fixtures_dir, *, redact: bool):
    worker_main = _load_worker_main()
    from common.settings import Settings

    cfg = get_default_config()
    cfg["privacy"]["redact_secrets"] = redact
    cfg["check_run"] = True
    cfg["summary_comment"] = True
    cfg["inline_comments"] = True

    captured: dict = {
        "check_run": None,
        "sticky": None,
        "inline": None,
    }

    def capture_check_run(*args, **kwargs):
        captured["check_run"] = {
            "findings": kwargs.get("findings"),
            "report_body": kwargs.get("report_body"),
        }
        return {"id": 99, "_action": "created"}

    def capture_sticky(*args, **kwargs):
        captured["sticky"] = {"report_body": kwargs.get("report_body")}
        return {"_action": "created", "comment_id": 1}

    def capture_inline(*args, **kwargs):
        captured["inline"] = {"findings": kwargs.get("findings")}
        return {"posted": 1}

    monkeypatch.setattr(worker_main, "get_analyzer", lambda config: _fake_analysis())
    monkeypatch.setattr(
        worker_main, "_load_job_config", lambda *a, **k: (cfg, [])
    )
    monkeypatch.setattr(worker_main, "publish_check_run", capture_check_run)
    monkeypatch.setattr(worker_main, "upsert_pr_comment", capture_sticky)
    monkeypatch.setattr(worker_main, "publish_inline_comments", capture_inline)

    settings = Settings(
        use_fixtures=True,
        fixtures_dir=str(fixtures_dir),
        github_token="",
    )
    job = {
        "owner": "acme",
        "repo": "demo",
        "pr_number": 7,
        "head_sha": "deadbeefcafebabe000011112222333344445555",
        "installation_id": None,
    }
    out = worker_main.process_job(job, settings)
    return out, captured


def test_outbound_redacted_when_privacy_on(fixtures_dir, monkeypatch):
    out, cap = _run_process_job(monkeypatch, fixtures_dir, redact=True)

    # Check Run
    cr = cap["check_run"]
    assert cr is not None
    assert AKIA not in (cr["report_body"] or "")
    assert REDACT_PLACEHOLDER in (cr["report_body"] or "")
    f0 = cr["findings"][0]
    assert AKIA not in f0.message
    assert AKIA not in (f0.detail or "")
    assert REDACT_PLACEHOLDER in f0.message
    assert f0.meta.get("match") == REDACT_PLACEHOLDER

    # Sticky comment
    sticky = cap["sticky"]
    assert sticky is not None
    assert AKIA not in (sticky["report_body"] or "")
    assert REDACT_PLACEHOLDER in (sticky["report_body"] or "")

    # Inline findings (human body source)
    inline = cap["inline"]
    assert inline is not None
    i0 = inline["findings"][0]
    assert AKIA not in i0.message
    assert AKIA not in (i0.detail or "")
    assert REDACT_PLACEHOLDER in i0.message

    # Return / storage payload
    assert AKIA not in out["report"]
    assert REDACT_PLACEHOLDER in out["report"]
    assert out["findings"][0]["meta"]["match"] == REDACT_PLACEHOLDER


def test_outbound_keeps_secrets_when_privacy_off(fixtures_dir, monkeypatch):
    out, cap = _run_process_job(monkeypatch, fixtures_dir, redact=False)

    cr = cap["check_run"]
    assert AKIA in (cr["report_body"] or "")
    assert AKIA in cr["findings"][0].message
    assert cr["findings"][0].meta.get("match") == AKIA

    assert AKIA in (cap["sticky"]["report_body"] or "")

    i0 = cap["inline"]["findings"][0]
    assert AKIA in i0.message
    assert i0.meta.get("match") == AKIA

    assert AKIA in out["report"]
    assert out["findings"][0]["meta"]["match"] == AKIA
