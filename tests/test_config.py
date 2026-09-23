"""Config deep_merge + default-branch / fixture loading."""

from __future__ import annotations

from pathlib import Path

from common.config import deep_merge, load_config_from_text, load_repo_config
from common.defaults import DEFAULT_CONFIG, get_default_config


def test_deep_merge_overlay_and_nested():
    base = get_default_config()
    overlay = {
        "update_strategy": "recreate",
        "diff": {"max_files": 10},
        "rules": {"large_files": {"max_bytes": 100}},
        "analyzer": {"mode": "rules"},
    }
    merged = deep_merge(base, overlay)
    assert merged["update_strategy"] == "recreate"
    assert merged["diff"]["max_files"] == 10
    assert merged["diff"]["max_pages"] == base["diff"]["max_pages"]  # preserved
    assert merged["rules"]["large_files"]["max_bytes"] == 100
    assert merged["rules"]["secrets"]["enabled"] is True  # preserved nested
    # base untouched
    assert DEFAULT_CONFIG["diff"]["max_files"] == 300


def test_load_config_missing_falls_back():
    cfg, notes = load_config_from_text(None)
    assert cfg["analyzer"]["mode"] == "rules"
    assert any("未找到" in n for n in notes)


def test_load_config_parse_failure_falls_back():
    cfg, notes = load_config_from_text("- just a list")
    assert cfg["version"] == 1
    assert any("解析" in n for n in notes)


def test_load_repo_config_from_fixture(fixtures_dir: Path):
    cfg, notes = load_repo_config(use_fixtures=True, fixtures_dir=fixtures_dir)
    assert cfg["analyzer"]["mode"] == "rules"
    assert cfg["rules"]["large_files"]["max_bytes"] == 500  # overlay from fixture
    assert any("fixture" in n for n in notes)


def test_load_repo_config_missing_fixture(tmp_path: Path):
    cfg, notes = load_repo_config(use_fixtures=True, fixtures_dir=tmp_path)
    assert cfg["diff"]["max_files"] == 300
    assert any("未找到" in n for n in notes)
