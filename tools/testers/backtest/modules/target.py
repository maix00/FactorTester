"""Common target-weight strategy state.

Concrete strategy modules such as group membership and long-short composition
produce target weights in different ways.  This module owns the shared,
long-lived state for those target-producing flows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldRef


class TargetStrategyModule(ExecutableModule):
    """Base class for modules that produce strategy target weights."""

    target_weights: ClassVar[FieldRef[Any]] = FieldRef("target_weights")


@dataclass
class TargetStore:
    strategy_established_target_weights: dict[Any, Any] = field(default_factory=dict)
    strategy_selection_cache: dict[Any, Any] = field(default_factory=dict)
    target_trace: dict[Any, dict[str, Any]] = field(default_factory=dict)

    def record_target_trace(self, strategy: Any, timestamp: Any, weights: dict[Any, Any]) -> None:
        if timestamp is None:
            return
        self.target_trace.setdefault(strategy, {})[timestamp.isoformat()] = {
            str(product): weight for product, weight in weights.items()
        }

    def target_trace_for(self, strategy: Any) -> dict[str, Any]:
        return dict(self.target_trace.get(strategy, {}))
