"""Pluggable rule engine for PR quality findings."""

from .base import Finding, Rule
from .dangerous_commands import DangerousCommandsRule
from .engine import RulesEngine, filter_ignored, run_rules
from .large_files import LargeFilesRule
from .secrets import SecretsRule
from .skipped_tests import SkippedTestsRule
from .weakened_tests import WeakenedTestsRule

__all__ = [
    "Finding",
    "Rule",
    "RulesEngine",
    "filter_ignored",
    "run_rules",
    "SecretsRule",
    "LargeFilesRule",
    "WeakenedTestsRule",
    "SkippedTestsRule",
    "DangerousCommandsRule",
]
