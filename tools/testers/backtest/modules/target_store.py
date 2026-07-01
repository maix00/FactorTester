from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TargetStore:
    established_target_weights: dict[Any, Any] = field(default_factory=dict)
    last_group_membership: dict[Any, Any] = field(default_factory=dict)
    target_trace: dict[Any, dict[str, Any]] = field(default_factory=dict)
    long_short_diagnostics: dict[Any, dict[str, Any]] = field(default_factory=dict)

    def record_target_trace(self, strategy: Any, timestamp: Any, weights: dict[Any, Any]) -> None:
        if timestamp is None:
            return
        self.target_trace.setdefault(strategy, {})[timestamp.isoformat()] = {
            str(product): weight for product, weight in weights.items()
        }

    def target_trace_for(self, strategy: Any) -> dict[str, Any]:
        return dict(self.target_trace.get(strategy, {}))

    def record_long_short_diagnostics(self, strategy: Any, timestamp: Any, diagnostics: dict[str, Any]) -> None:
        if timestamp is None:
            return
        self.long_short_diagnostics.setdefault(strategy, {})[timestamp.isoformat()] = dict(diagnostics)
