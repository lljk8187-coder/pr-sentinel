"""Run built-in rules after ignore_paths filtering."""

from __future__ import annotations

from typing import Any

from .base import Finding, Rule
from .ignore_paths import filter_ignored
from .large_files import LargeFilesRule
from .secrets import SecretsRule
from .weakened_tests import WeakenedTestsRule

# Re-export for convenience
__all__ = ["RulesEngine", "filter_ignored", "run_rules", "default_rules"]


def default_rules() -> list[Rule]:
    return [SecretsRule(), LargeFilesRule(), WeakenedTestsRule()]


def run_rules(
    files: list[dict[str, Any]],
    config: dict[str, Any],
    rules: list[Rule] | None = None,
) -> tuple[list[Finding], list[dict[str, Any]], list[dict[str, Any]]]:
    """Filter ignored paths, then run rules on remaining files.

    Returns ``(findings, kept_files, ignored_files)``.
    """
    kept, ignored = filter_ignored(files, config)
    plugins = rules if rules is not None else default_rules()
    findings: list[Finding] = []
    for rule in plugins:
        findings.extend(rule.check(kept, config))
    return findings, kept, ignored


class RulesEngine:
    def __init__(self, rules: list[Rule] | None = None):
        self.rules = rules if rules is not None else default_rules()

    def run(
        self, files: list[dict[str, Any]], config: dict[str, Any]
    ) -> tuple[list[Finding], list[dict[str, Any]], list[dict[str, Any]]]:
        return run_rules(files, config, self.rules)
