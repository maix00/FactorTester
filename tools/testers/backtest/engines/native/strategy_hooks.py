"""Small public strategy-hook protocol over the native Flow runtime."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Iterable

import pandas as pd

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.market_events import MarketFeedEventKind
from tools.testers.backtest.engines.native.strategy_commands import (
    CancelOrderCommand,
    ClosePositionCommand,
    ReplaceOrderCommand,
    SubmitOrderCommand,
    StrategyCommand,
)
from tools.testers.backtest.engines.native.timer_events import TimerCancel, TimerSchedule
if TYPE_CHECKING:
    from tools.testers.backtest.modules.target import OrderDeltaIntent, TargetWeightIntent


StrategyIntent = Any


@dataclass(frozen=True)
class StrategyRequirements:
    feed_events: frozenset[MarketFeedEventKind] = frozenset()
    needs_partial_fills: bool = False
    needs_order_events: bool = False
    needs_order_status_events: bool = False
    needs_position_events: bool = False
    needs_timer_events: bool = False


@dataclass(frozen=True)
class ExecutionCapabilities:
    feed_events: frozenset[MarketFeedEventKind] = frozenset()
    partial_fills: bool = False
    order_events: bool = False
    order_status_events: bool = False
    position_events: bool = False
    timer_events: bool = False


def validate_strategy_capabilities(
    requirements: StrategyRequirements,
    capabilities: ExecutionCapabilities,
) -> dict[str, Any]:
    missing_events = sorted(
        event.value for event in requirements.feed_events - capabilities.feed_events
    )
    errors: list[str] = []
    if missing_events:
        errors.append(f"missing market events: {', '.join(missing_events)}")
    if requirements.needs_partial_fills and not capabilities.partial_fills:
        errors.append("strategy requires partial fills")
    if requirements.needs_order_events and not capabilities.order_events:
        errors.append("strategy requires order lifecycle events")
    if requirements.needs_order_status_events and not capabilities.order_status_events:
        errors.append("strategy requires order status events")
    if requirements.needs_position_events and not capabilities.position_events:
        errors.append("strategy requires position lifecycle events")
    if requirements.needs_timer_events and not capabilities.timer_events:
        errors.append("strategy requires timer events")
    return {
        "ok": not errors,
        "missing_feed_events": missing_events,
        "errors": errors,
    }


@dataclass(frozen=True)
class StrategyContext:
    """Read-only view passed to user hooks.

    The queue and FlowContext are intentionally private.  Trading intents are
    scheduled as SIGNAL events; timer controls are handled by the clock-owned
    scheduler.  Neither path grants direct access to sizing, risk, execution,
    fees, margin or ledger state.
    """

    strategy: Any
    timestamp: pd.Timestamp | None
    event_kind: EventKind | None
    positions: Mapping[Any, Any]
    current_prices: Mapping[Any, Any]
    run_start: pd.Timestamp | None = None
    run_end: pd.Timestamp | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "positions", MappingProxyType(dict(self.positions)))
        object.__setattr__(self, "current_prices", MappingProxyType(dict(self.current_prices)))

    def target_weights(self, weights: dict[Any, float], *, reason: str = "hook") -> Any:
        from tools.testers.backtest.modules.target import TargetWeightIntent

        return TargetWeightIntent(dict(weights), reason=reason)

    def order_deltas(self, deltas: dict[Any, float], *, reason: str = "hook") -> Any:
        from tools.testers.backtest.modules.target import OrderDeltaIntent

        return OrderDeltaIntent(dict(deltas), reason=reason)

    def submit_order(self, product: Any, quantity: float, *, side: str = "buy", reason: str = "submit_order") -> StrategyCommand:
        return SubmitOrderCommand(product, quantity, side=side, reason=reason)

    def cancel_order(self, order_id: str, *, reason: str = "cancel_order") -> StrategyCommand:
        return CancelOrderCommand(order_id, reason=reason)

    def replace_order(self, order_id: str, quantity: float, *, reason: str = "replace_order") -> StrategyCommand:
        return ReplaceOrderCommand(order_id, quantity, reason=reason)

    def close_position(self, product: Any, quantity: float | None = None, *, reason: str = "close_position") -> StrategyCommand:
        return ClosePositionCommand(product, quantity=quantity, reason=reason)

    def set_timer(
        self,
        name: str,
        interval: pd.Timedelta,
        *,
        start_at: pd.Timestamp | None = None,
        end_at: pd.Timestamp | None = None,
    ) -> TimerSchedule:
        """Schedule a recurring clock event without exposing the event queue."""

        first = start_at if start_at is not None else self.timestamp or self.run_start
        if first is None:
            raise ValueError("set_timer requires start_at outside a bounded run")
        end = end_at if end_at is not None else self.run_end
        if end is None:
            raise ValueError("set_timer requires end_at outside a bounded run")
        return TimerSchedule(name, pd.Timestamp(first), pd.Timedelta(interval), pd.Timestamp(end))

    def set_time_alert(self, name: str, alert_at: pd.Timestamp) -> TimerSchedule:
        """Schedule one clock event at an absolute timestamp."""

        return TimerSchedule(name, pd.Timestamp(alert_at))

    def cancel_timer(self, name: str) -> TimerCancel:
        return TimerCancel(name)


def normalize_hook_result(result: Any) -> tuple[StrategyIntent, ...]:
    """Accept one intent or a short iterable, never arbitrary queue objects."""

    from tools.testers.backtest.modules.target import OrderDeltaIntent, TargetWeightIntent

    if result is None:
        return ()
    if isinstance(result, (TargetWeightIntent, OrderDeltaIntent, SubmitOrderCommand, CancelOrderCommand, ReplaceOrderCommand, ClosePositionCommand, TimerSchedule, TimerCancel)):
        return (result,)
    if isinstance(result, Iterable) and not isinstance(result, (str, bytes, dict)):
        values = tuple(result)
        if not all(isinstance(value, (TargetWeightIntent, OrderDeltaIntent, SubmitOrderCommand, CancelOrderCommand, ReplaceOrderCommand, ClosePositionCommand, TimerSchedule, TimerCancel)) for value in values):
            raise TypeError("strategy hook iterable must contain typed intents or commands")
        return values
    raise TypeError(
        "strategy hook must return typed intents: TargetWeightIntent, "
        "OrderDeltaIntent, StrategyCommand, an iterable of those, or None"
    )


def intent_payload(intent: StrategyIntent) -> dict[str, Any]:
    """Stable serializable payload used by a queued SIGNAL event."""

    from tools.testers.backtest.modules.target import OrderDeltaIntent, TargetWeightIntent

    if isinstance(intent, (TimerSchedule, TimerCancel)):
        raise TypeError("timer controls are not strategy SIGNAL intents")

    if isinstance(intent, (SubmitOrderCommand, CancelOrderCommand, ReplaceOrderCommand, ClosePositionCommand)):
        from tools.testers.backtest.engines.native.strategy_commands import command_payload

        return command_payload(intent)

    if isinstance(intent, TargetWeightIntent):
        return {
            "kind": "strategy_runtime_intent",
            "intent_kind": "target_weights",
            "weights": dict(intent.weights),
            "reason": intent.reason,
        }
    return {
        "kind": "strategy_runtime_intent",
        "intent_kind": "order_deltas",
        "deltas": dict(intent.deltas),
        "reason": intent.reason,
    }
