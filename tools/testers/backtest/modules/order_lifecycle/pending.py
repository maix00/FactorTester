"""Pending-order conflict policy for legacy scheduling."""

from __future__ import annotations

from typing import Any

from tools.testers.backtest.engines.native.order import OrderStatus


def default_pending_order_conflict_policy(
    state: Any,
    strategy: Any,
    order: Any,
    signal_timestamp: Any,
) -> None:
    pending = state.order_store.pending_orders
    stale = pending.get((strategy, order.instrument))
    if (
        stale is not None
        and stale.status == OrderStatus.SCHEDULED
        and stale.get("price_timestamp", stale.timestamp) > signal_timestamp
    ):
        stale.status = OrderStatus.CANCELLED
        stale.revision += 1
        state.order_store.remove_from_live_indexes(stale)
