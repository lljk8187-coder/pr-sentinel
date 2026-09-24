"""M28: ignore_paths empty-list contract — no filter; md files kept for secrets."""

from __future__ import annotations

from common.config import load_config_from_text
from common.defaults import get_default_config
from pr_sentinel_github.rules import RulesEngine, filter_ignored


def test_m28_empty_ignore_paths_keeps_md_for_secrets():
    """ignore_paths: [] replaces defaults → README.md / notes.md kept and secrets-scanned."""
    cfg = get_default_config()
    cfg["ignore_paths"] = []
    files = [
        {
            "filename": "README.md",
            "additions": 1,
            "deletions": 0,
            "patch": "@@ -0,0 +1 @@\n+AWS_KEY=AKIAIOSFODNN7EXAMPLE\n",
        },
        {
            "filename": "notes.md",
            "additions": 1,
            "deletions": 0,
            "patch": "@@ -0,0 +1 @@\n+AWS_KEY=AKIAIOSFODNN7EXAMPLE\n",
        },
        {
            "filename": "src/app.py",
            "additions": 1,
            "deletions": 0,
            "patch": "@@ -0,0 +1 @@\n+print('ok')\n",
        },
    ]
    kept, ignored = filter_ignored(files, cfg)
    names_kept = {f["filename"] for f in kept}
    assert ignored == []
    assert "README.md" in names_kept
    assert "notes.md" in names_kept
    assert "src/app.py" in names_kept

    findings, kept2, ignored2 = RulesEngine().run(files, cfg)
    assert ignored2 == []
    secret_paths = {f.filename for f in findings if f.rule_id == "secrets"}
    assert "README.md" in secret_paths
    assert "notes.md" in secret_paths


def test_m28_yaml_empty_list_replaces_default_ignore_paths():
    """deep_merge list overlay: ignore_paths: [] must not keep default docs/** / **/*.md."""
    cfg, notes = load_config_from_text("ignore_paths: []\n")
    assert cfg["ignore_paths"] == []
    assert any("深度合并" in n for n in notes)

    files = [{"filename": "README.md", "additions": 1, "patch": "+x"}]
    kept, ignored = filter_ignored(files, cfg)
    assert len(kept) == 1 and kept[0]["filename"] == "README.md"
    assert ignored == []
