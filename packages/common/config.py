"""Load and merge `.pr-sentinel.yml` from the repository default branch."""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any, Callable

import yaml

from .defaults import get_default_config

logger = logging.getLogger(__name__)

CONFIG_FILENAME = ".pr-sentinel.yml"


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *overlay* onto a deep copy of *base*.

    Nested dicts are merged; lists and scalars from overlay replace base.
    """
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def parse_yaml_config(text: str) -> dict[str, Any]:
    """Parse YAML text into a dict. Empty / non-mapping → {}."""
    data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("config root must be a mapping")
    return data


def load_config_from_text(
    text: str | None,
    *,
    source_note: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Merge DEFAULT_CONFIG with parsed YAML text.

    Returns ``(config, notes)`` where *notes* describe fallbacks / overlays
    for inclusion in the analysis report.
    """
    notes: list[str] = []
    base = get_default_config()
    if text is None:
        notes.append("未找到 `.pr-sentinel.yml`，仅使用内置 DEFAULT_CONFIG。")
        return base, notes
    try:
        overlay = parse_yaml_config(text)
    except Exception as exc:  # noqa: BLE001 — report parse errors, don't crash job
        notes.append(f"解析 `.pr-sentinel.yml` 失败（{exc}），仅使用内置 DEFAULT_CONFIG。")
        return base, notes
    if not overlay:
        notes.append("`.pr-sentinel.yml` 为空，仅使用内置 DEFAULT_CONFIG。")
        return base, notes
    merged = deep_merge(base, overlay)
    src = source_note or "default branch `.pr-sentinel.yml`"
    notes.append(f"已与 {src} 深度合并。")
    return merged, notes


def load_repo_config(
    *,
    fetch_yml: Callable[[], str | None] | None = None,
    fixtures_dir: Path | str | None = None,
    use_fixtures: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    """Load config: fixtures file, or *fetch_yml* (default-branch API), else defaults.

    PR-branch config is intentionally **ignored** — caller must pass a fetch
    that reads the repository default branch only.
    """
    if use_fixtures and fixtures_dir is not None:
        path = Path(fixtures_dir) / "pr-sentinel.yml"
        alt = Path(fixtures_dir) / CONFIG_FILENAME
        chosen = path if path.exists() else alt if alt.exists() else None
        if chosen is None:
            return load_config_from_text(None)
        try:
            text = chosen.read_text(encoding="utf-8")
        except OSError as exc:
            return load_config_from_text(None)[0], [
                f"读取 fixture 配置失败（{exc}），仅使用内置 DEFAULT_CONFIG。"
            ]
        return load_config_from_text(text, source_note=f"fixture `{chosen.name}`")

    if fetch_yml is not None:
        try:
            text = fetch_yml()
        except Exception as exc:  # noqa: BLE001
            logger.warning("fetch .pr-sentinel.yml failed: %s", exc)
            cfg, notes = load_config_from_text(None)
            notes = [
                f"拉取 default branch `.pr-sentinel.yml` 失败（{exc}），仅使用内置 DEFAULT_CONFIG。"
            ]
            return cfg, notes
        return load_config_from_text(
            text, source_note="default branch `.pr-sentinel.yml`"
        )

    return load_config_from_text(None)
