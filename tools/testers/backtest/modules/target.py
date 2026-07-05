"""Common strategy intent state.

Concrete strategy modules such as group membership, long-short composition, or
technical rules produce trade intents in different ways. Target weights are one
intent representation, not the universal strategy abstraction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldRef


@dataclass(frozen=True)
class TargetWeightIntent:
    weights: dict[Any, float]
    reason: str = "target_weights"


@dataclass(frozen=True)
class OrderDeltaIntent:
    deltas: dict[Any, float]
    reason: str = "order_deltas"


class TargetStrategyModule(ExecutableModule):
    """Base class for modules that produce strategy trade intents."""

    trade_intent: ClassVar[FieldRef[Any]] = FieldRef("trade_intent")
    target_weights: ClassVar[FieldRef[Any]] = FieldRef("target_weights")


def target_weight_intent(weights: dict[Any, float], *, reason: str) -> TargetWeightIntent:
    return TargetWeightIntent(dict(weights), reason=reason)


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
