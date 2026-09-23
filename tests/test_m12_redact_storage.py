"""M12b: redact secrets before findings/report persistence."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from common.defaults import get_default_config
from pr_sentinel_github.llm import REDACT_PLACEHOLDER, redact_findings_for_storage


AKIA = "AKIAIOSFODNN7EXAMPLE"


def test_redact_findings_message_detail_meta_match_and_report():
    cfg = get_default_config()
    findings = [
        {
            "rule_id": "secrets",
            "severity": "error",
            "message": f"found key {AKIA}",
            "title": f"found key {AKIA}",
            "detail": f"match around {AKIA} here",
            "path": "cfg.env",
            "filename": "cfg.env",
            "meta": {"match": AKIA, "pattern": r"AKIA[0-9A-Z]{16}", "nested": {"x": AKIA}},
            "source": "rules",
        }
    ]
    report = f"# Report\n\nSecret leaked: {AKIA}\n"
    out_f, out_r = redact_findings_for_storage(findings, report, cfg)
    assert AKIA not in out_f[0]["message"]
    assert AKIA not in out_f[0]["detail"]
    assert AKIA not in out_f[0]["title"]
    assert out_f[0]["meta"]["match"] == REDACT_PLACEHOLDER
    assert out_f[0]["meta"]["nested"]["x"] == REDACT_PLACEHOLDER
    assert REDACT_PLACEHOLDER in out_f[0]["message"]
    assert AKIA not in (out_r or "")
    assert REDACT_PLACEHOLDER in (out_r or "")
    # original untouched
    assert findings[0]["meta"]["match"] == AKIA


def test_redact_disabled_keeps_secrets():
    cfg = get_default_config()
    cfg["privacy"]["redact_secrets"] = False
    findings = [
        {
            "message": AKIA,
            "detail": AKIA,
            "meta": {"match": AKIA},
        }
    ]
    out_f, out_r = redact_findings_for_storage(findings, f"r {AKIA}", cfg)
    assert out_f[0]["message"] == AKIA
    assert out_f[0]["meta"]["match"] == AKIA
    assert AKIA in (out_r or "")


def test_process_job_redacts_findings_before_return(fixtures_dir, monkeypatch):
    """process_job result findings/report used for PG writeback are redacted."""
    root = Path(__file__).resolve().parents[1]
    path = root / "apps" / "worker" / "main.py"
    spec = importlib.util.spec_from_file_location("pr_sentinel_worker_main_m12", path)
    assert spec and spec.loader
    worker_main = importlib.util.module_from_spec(spec)
    for pth in (root, root / "packages", root / "packages" / "github"):
        sp = str(pth)
        if sp not in sys.path:
            sys.path.insert(0, sp)
    spec.loader.exec_module(worker_main)

    from common.settings import Settings
    from pr_sentinel_github.rules.base import Finding

    class _FakeAnalysis:
        markdown = f"# PR Sentinel\n\nAWS {AKIA}\n"
        findings = [
            Finding(
                rule_id="secrets",
                severity="error",
                message=f"疑似密钥 {AKIA}",
                filename="leak.env",
                detail=f"detail {AKIA}",
                meta={"match": AKIA, "pattern": "AKIA"},
            )
        ]

    class _FakeAnalyzer:
        def analyze(self, *args, **kwargs):
            return _FakeAnalysis()

    monkeypatch.setattr(worker_main, "get_analyzer", lambda config: _FakeAnalyzer())
    monkeypatch.setattr(
        worker_main,
        "publish_check_run",
        lambda *a, **k: {"id": 1, "_action": "created"},
    )
    monkeypatch.setattr(
        worker_main,
        "publish_inline_comments",
        lambda *a, **k: {"posted": 0},
    )
    monkeypatch.setattr(
        worker_main,
        "upsert_pr_comment",
        lambda *a, **k: {"_action": "created", "comment_id": 1},
    )

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
    assert isinstance(out.get("findings"), list)
    assert out["findings"]
    f0 = out["findings"][0]
    assert AKIA not in f0["message"]
    assert AKIA not in f0.get("detail", "")
    assert f0["meta"]["match"] == REDACT_PLACEHOLDER
    assert AKIA not in out["report"]
    assert REDACT_PLACEHOLDER in out["report"]
