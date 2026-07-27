"""Small public strategy-hook protocol over the native Flow runtime."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Iterable

import pandas as pd

from tools.testers.backtest.engines.native.events import EventKind
if TYPE_CHECKING:
    from tools.testers.backtest.modules.target import OrderDeltaIntent, TargetWeightIntent


StrategyIntent = Any


@dataclass(frozen=True)
class StrategyContext:
    """Read-only view passed to user hooks.

    The queue and FlowContext are intentionally private.  Hooks return typed
    intents; the adapter schedules them as SIGNAL events so sizing, risk,
    execution, fees, margin and ledger ownership remain unchanged.
    """

    strategy: Any
    timestamp: pd.Timestamp | None
    event_kind: EventKind | None
    positions: Mapping[Any, Any]
    current_prices: Mapping[Any, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "positions", MappingProxyType(dict(self.positions)))
        object.__setattr__(self, "current_prices", MappingProxyType(dict(self.current_prices)))

    def target_weights(self, weights: dict[Any, float], *, reason: str = "hook") -> Any:
        from tools.testers.backtest.modules.target import TargetWeightIntent

        return TargetWeightIntent(dict(weights), reason=reason)

    def order_deltas(self, deltas: dict[Any, float], *, reason: str = "hook") -> Any:
        from tools.testers.backtest.modules.target import OrderDeltaIntent

        return OrderDeltaIntent(dict(deltas), reason=reason)


def normalize_hook_result(result: Any) -> tuple[StrategyIntent, ...]:
    """Accept one intent or a short iterable, never arbitrary queue objects."""

    from tools.testers.backtest.modules.target import OrderDeltaIntent, TargetWeightIntent

    if result is None:
        return ()
    if isinstance(result, (TargetWeightIntent, OrderDeltaIntent)):
        return (result,)
    if isinstance(result, Iterable) and not isinstance(result, (str, bytes, dict)):
        values = tuple(result)
        if not all(isinstance(value, (TargetWeightIntent, OrderDeltaIntent)) for value in values):
            raise TypeError("strategy hook iterable must contain typed intents")
        return values
    raise TypeError(
        "strategy hook must return TargetWeightIntent, OrderDeltaIntent, "
        "an iterable of those, or None"
    )


def intent_payload(intent: StrategyIntent) -> dict[str, Any]:
    """Stable serializable payload used by a queued SIGNAL event."""

    from tools.testers.backtest.modules.target import OrderDeltaIntent, TargetWeightIntent

    if isinstance(intent, TargetWeightIntent):
        return {
            "kind": "strategy_hook_intent",
            "intent_kind": "target_weights",
            "weights": dict(intent.weights),
            "reason": intent.reason,
        }
    return {
        "kind": "strategy_hook_intent",
        "intent_kind": "order_deltas",
        "deltas": dict(intent.deltas),
        "reason": intent.reason,
    }
