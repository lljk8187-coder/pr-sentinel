"""Load and merge `.pr-sentinel.yml` from the repository default branch."""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any, Callable

import yaml

from .defaults import DEFAULT_CONFIG, get_default_config

logger = logging.getLogger(__name__)

CONFIG_FILENAME = ".pr-sentinel.yml"

UPDATE_STRATEGY_VALUES = frozenset({"update", "recreate", "skip_if_exists"})
ANALYZER_MODE_VALUES = frozenset({"rules", "rules+llm", "fake"})


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


def _type_ok(expected: Any, actual: Any) -> bool:
    """Return True if *actual* is acceptable for a DEFAULT_CONFIG leaf *expected*."""
    if isinstance(expected, bool):
        return isinstance(actual, bool)
    if isinstance(expected, int) and not isinstance(expected, bool):
        # YAML ints; reject bool (bool is subclass of int)
        return isinstance(actual, int) and not isinstance(actual, bool)
    if isinstance(expected, float):
        return (isinstance(actual, (int, float)) and not isinstance(actual, bool))
    if isinstance(expected, str):
        return isinstance(actual, str)
    if isinstance(expected, list):
        return isinstance(actual, list)
    if isinstance(expected, dict):
        return isinstance(actual, dict)
    return type(actual) is type(expected)


def validate_config(config: dict[str, Any]) -> list[str]:
    """Sanitize *config* in-place against ``DEFAULT_CONFIG`` shape; return notes.

    - Unknown keys at any mapping layer (top-level or nested) → stripped + note
      with dotted path (e.g. ``diff.nope``, ``rules.secrets.typo_key``)
    - Type mismatches → key reverted to DEFAULT + note
    - Enums: ``update_strategy``, ``analyzer.mode`` → invalid → default + note
    - Nested dicts walk known paths; list leaves are not schema-walked; never raises
    """
    notes: list[str] = []
    if not isinstance(config, dict):
        notes.append("配置根类型无效，已回退到 DEFAULT_CONFIG。")
        return notes

    defaults = DEFAULT_CONFIG

    def walk(cfg: dict[str, Any], dft: dict[str, Any], path: str) -> None:
        # Strip unknown keys at this mapping layer (including root)
        unknown = [k for k in list(cfg.keys()) if k not in dft]
        for key in unknown:
            loc = f"{path}.{key}" if path else key
            del cfg[key]
            notes.append(f"忽略未知配置项 `{loc}`。")

        for key, default_val in dft.items():
            loc = f"{path}.{key}" if path else key
            if key not in cfg:
                continue
            actual = cfg[key]

            if isinstance(default_val, dict):
                if not isinstance(actual, dict):
                    cfg[key] = copy.deepcopy(default_val)
                    notes.append(
                        f"配置项 `{loc}` 类型错误（期望 mapping），已回退为默认值。"
                    )
                    continue
                walk(actual, default_val, loc)
                continue

            if not _type_ok(default_val, actual):
                cfg[key] = copy.deepcopy(default_val)
                notes.append(
                    f"配置项 `{loc}` 类型错误（期望 {type(default_val).__name__}），"
                    f"已回退为默认值 {default_val!r}。"
                )

    walk(config, defaults, "")

    # Enums (after type walk so value is at least a str when valid-typed)
    strategy = config.get("update_strategy")
    if isinstance(strategy, str) and strategy not in UPDATE_STRATEGY_VALUES:
        config["update_strategy"] = copy.deepcopy(defaults["update_strategy"])
        notes.append(
            f"配置项 `update_strategy` 非法值 {strategy!r}，"
            f"已回退为默认值 {defaults['update_strategy']!r}。"
        )

    analyzer = config.get("analyzer")
    if isinstance(analyzer, dict):
        mode = analyzer.get("mode")
        if isinstance(mode, str) and mode not in ANALYZER_MODE_VALUES:
            analyzer["mode"] = copy.deepcopy(defaults["analyzer"]["mode"])
            notes.append(
                f"配置项 `analyzer.mode` 非法值 {mode!r}，"
                f"已回退为默认值 {defaults['analyzer']['mode']!r}。"
            )

    return notes


def load_config_from_text(
    text: str | None,
    *,
    source_note: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Merge DEFAULT_CONFIG with parsed YAML text.

    Returns ``(config, notes)`` where *notes* describe fallbacks / overlays
    for inclusion in the analysis report. Invalid field values never fail the
    job — they fall back to defaults with Chinese notes.
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

    # Validate overlay shape first (strip unknown keys at any layer / bad types),
    # then merge; validate again on merged so nested defaults stay consistent.
    overlay_notes = validate_config(overlay)
    notes.extend(overlay_notes)
    merged = deep_merge(base, overlay)
    # Re-validate merged (enums / types that deep_merge may have carried)
    merge_notes = validate_config(merged)
    # Avoid duplicate notes for the same message
    for n in merge_notes:
        if n not in notes:
            notes.append(n)
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
