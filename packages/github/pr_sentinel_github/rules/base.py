"""Rule plugin interface and Finding model."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


@dataclass
class Finding:
    rule_id: str
    severity: str  # info | warning | error
    message: str
    filename: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Rule(Protocol):
    """Plugin interface: ``check(files, config) -> list[Finding]``."""

    rule_id: str

    def check(
        self, files: list[dict[str, Any]], config: dict[str, Any]
    ) -> list[Finding]: ...
