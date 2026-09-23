"""Rule plugin interface and Finding model."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


@dataclass
class Finding:
    """Unified finding from rules engine or LLM.

    Suggested shape: ``{source, severity, title, detail, path?, line?}``.
    ``message`` / ``filename`` / ``rule_id`` kept for M2 rule compatibility.
    """

    rule_id: str
    severity: str  # info | warning | error | low | medium | high | critical
    message: str
    filename: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    source: str = "rules"  # rules | llm
    detail: str = ""
    line: int | None = None

    @property
    def title(self) -> str:
        return self.message

    @property
    def path(self) -> str | None:
        return self.filename

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["title"] = self.title
        d["path"] = self.path
        return d


class Rule(Protocol):
    """Plugin interface: ``check(files, config) -> list[Finding]``."""

    rule_id: str

    def check(
        self, files: list[dict[str, Any]], config: dict[str, Any]
    ) -> list[Finding]: ...
