"""Apply typed commands at the strategy-to-order boundary."""

from __future__ import annotations

from typing import Any

from tools.testers.backtest.engines.native.order import OrderActionType, OrderStatus
from tools.testers.backtest.engines.native.strategy_commands import (
    CancelOrderCommand,
    ClosePositionCommand,
    ReplaceOrderCommand,
    SubmitOrderCommand,
    StrategyCommand,
)
from tools.testers.backtest.modules.order_lifecycle import (
    order_stores_for,
    record_order_action,
)
from tools.testers.backtest.modules.strategy_book import positions_for_strategy_ledgers
from tools.testers.backtest.modules.target import OrderDeltaIntent


def apply_strategy_command(state: Any, strategy: Any, command: StrategyCommand, timestamp: Any) -> Any:
    """Apply one command without granting a hook access to runtime services."""

    if isinstance(command, SubmitOrderCommand):
        return _submit_intent(command)
    if isinstance(command, ClosePositionCommand):
        return _close_intent(state, strategy, command)
    if isinstance(command, CancelOrderCommand):
        _cancel_order(state, strategy, command, timestamp)
        return None
    if isinstance(command, ReplaceOrderCommand):
        return _replace_intent(state, strategy, command, timestamp)
    raise TypeError(f"unsupported strategy command: {type(command).__name__}")


def _submit_intent(command: SubmitOrderCommand) -> OrderDeltaIntent:
    sign = 1.0 if command.side.value == "buy" else -1.0
    return OrderDeltaIntent({command.product: sign * float(command.quantity)}, reason=command.reason)


def _close_intent(state: Any, strategy: Any, command: ClosePositionCommand) -> OrderDeltaIntent | None:
    positions = positions_for_strategy_ledgers(state, strategy)
    position = positions.get(command.product)
    current = float(getattr(position, "quantity", 0.0) or 0.0)
    if abs(current) <= 1e-12:
        return None
    quantity = abs(current) if command.quantity is None else min(abs(current), float(command.quantity))
    return OrderDeltaIntent(
        {command.product: (-1.0 if current > 0 else 1.0) * quantity},
        reason=command.reason,
    )


def _cancel_order(state: Any, strategy: Any, command: CancelOrderCommand, timestamp: Any) -> None:
    order_store, _ = order_stores_for(state)
    order = order_store.orders_by_id.get(command.order_id)
    if order is None:
        raise ValueError(f"unknown order_id: {command.order_id!r}")
    if order.strategy is not strategy:
        raise ValueError("strategy cannot cancel another strategy's order")
    if order.status.terminal:
        return
    order.revision += 1
    record_order_action(
        state,
        order,
        OrderActionType.CANCEL,
        timestamp=timestamp,
        reason=command.reason,
    )
    order.status = OrderStatus.CANCELLED
    order_store.remove_from_live_indexes(order)
    pending = order_store.pending_orders
    scope = (strategy, order.instrument)
    if pending.get(scope) is order:
        pending.pop(scope, None)


def _replace_intent(
    state: Any,
    strategy: Any,
    command: ReplaceOrderCommand,
    timestamp: Any,
) -> OrderDeltaIntent | None:
    order_store, _ = order_stores_for(state)
    order = order_store.orders_by_id.get(command.order_id)
    if order is None:
        raise ValueError(f"unknown order_id: {command.order_id!r}")
    if order.strategy is not strategy:
        raise ValueError("strategy cannot replace another strategy's order")
    if order.status.terminal:
        return None
    side = order.side
    filled = float(order.filled_quantity or 0.0)
    remaining = max(float(command.quantity) - filled, 0.0)
    _cancel_order(state, strategy, CancelOrderCommand(command.order_id, command.reason), timestamp)
    if remaining <= 1e-12:
        return None
    sign = 1.0 if getattr(side, "value", side) == "buy" else -1.0
    return OrderDeltaIntent({order.instrument: sign * remaining}, reason=command.reason)
