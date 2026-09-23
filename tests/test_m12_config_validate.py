"""M12a: hand-written validate_config — bad yml → notes + defaults, never crash."""

from __future__ import annotations

from common.config import load_config_from_text, validate_config
from common.defaults import DEFAULT_CONFIG, get_default_config


def test_validate_unknown_top_level_stripped():
    cfg = get_default_config()
    cfg["not_a_real_key"] = 123
    notes = validate_config(cfg)
    assert "not_a_real_key" not in cfg
    assert any("not_a_real_key" in n for n in notes)


def test_validate_type_mismatch_summary_comment():
    cfg = get_default_config()
    cfg["summary_comment"] = "yes"
    notes = validate_config(cfg)
    assert cfg["summary_comment"] is True
    assert any("summary_comment" in n for n in notes)


def test_validate_type_mismatch_diff_max_pages():
    cfg = get_default_config()
    cfg["diff"]["max_pages"] = "x"
    notes = validate_config(cfg)
    assert cfg["diff"]["max_pages"] == DEFAULT_CONFIG["diff"]["max_pages"]
    assert any("diff.max_pages" in n for n in notes)


def test_validate_bad_update_strategy_enum():
    cfg = get_default_config()
    cfg["update_strategy"] = "upsert_please"
    notes = validate_config(cfg)
    assert cfg["update_strategy"] == "update"
    assert any("update_strategy" in n for n in notes)


def test_validate_bad_analyzer_mode_enum():
    cfg = get_default_config()
    cfg["analyzer"]["mode"] = "chatgpt"
    notes = validate_config(cfg)
    assert cfg["analyzer"]["mode"] == "rules+llm"
    assert any("analyzer.mode" in n for n in notes)


def test_validate_privacy_redact_secrets_bad_type():
    cfg = get_default_config()
    cfg["privacy"]["redact_secrets"] = "yes"
    notes = validate_config(cfg)
    assert cfg["privacy"]["redact_secrets"] is True
    assert any("privacy.redact_secrets" in n for n in notes)


def test_load_config_malformed_values_notes_and_defaults():
    yml = """
summary_comment: "yes"
diff:
  max_pages: "x"
  max_files: 12
update_strategy: totally_wrong
analyzer:
  mode: nope
privacy:
  redact_secrets: 1
extra_top: true
"""
    cfg, notes = load_config_from_text(yml)
    assert cfg["summary_comment"] is True
    assert cfg["diff"]["max_pages"] == DEFAULT_CONFIG["diff"]["max_pages"]
    assert cfg["diff"]["max_files"] == 12  # valid overlay kept
    assert cfg["update_strategy"] == "update"
    assert cfg["analyzer"]["mode"] == "rules+llm"
    assert cfg["privacy"]["redact_secrets"] is True
    assert "extra_top" not in cfg
    assert any("summary_comment" in n or "类型错误" in n for n in notes)
    assert any("update_strategy" in n for n in notes)
    assert any("analyzer.mode" in n for n in notes)
    assert any("extra_top" in n for n in notes)
    assert any("深度合并" in n for n in notes)


def test_load_config_still_succeeds_on_garbage_types():
    """Job must never crash on illegal yml values."""
    cfg, notes = load_config_from_text("check_run: [1,2,3]\ninline_comments: {}\n")
    assert isinstance(cfg, dict)
    assert cfg["check_run"] is True
    assert cfg["inline_comments"] is True
    assert notes  # has validation notes
