"""Pending-order conflict policy for legacy scheduling."""

from __future__ import annotations

from typing import Any

from tools.testers.backtest.engines.native.order import (
    OrderActionType,
    OrderStatus,
)

from .actions import record_order_action


def default_pending_order_conflict_policy(
    state: Any,
    strategy: Any,
    order: Any,
    signal_timestamp: Any,
) -> None:
    pending = state.order_store.pending_orders
    stale = pending.get((strategy, order.instrument))
    if stale is not None and stale.order_group_id == order.order_group_id:
        return
    if (
        stale is not None
        and stale.status in {OrderStatus.SUBMITTED, OrderStatus.ACCEPTED}
        and stale.get("price_timestamp", stale.timestamp) > signal_timestamp
    ):
        stale.revision += 1
        record_order_action(
            state, stale, OrderActionType.CANCEL,
            timestamp=signal_timestamp, reason="pending order conflict",
        )
        stale.status = OrderStatus.CANCELLED
        state.order_store.remove_from_live_indexes(stale)
