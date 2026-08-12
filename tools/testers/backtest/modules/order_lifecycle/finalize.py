"""Audit terminal and live states after one ORDER dispatch."""

from __future__ import annotations

from typing import Any

from tools.testers.backtest.engines.native.order import OrderStatus


def record_order_lifecycle_state(state: Any, ctx: Any) -> None:
    store = state.order_flow_store
    for strategy in ctx.active_strategies:
        for order in ctx.payloads_for(strategy):
            if order.status is OrderStatus.REJECTED:
                store.record(
                    order,
                    step="order_terminal",
                    label="订单拒绝",
                    timestamp=ctx.timestamp,
                    details={"reject_reason": str(order.reject_reason or order.get("reject_reason") or "")},
                )
            elif order.status is OrderStatus.CANCELLED:
                store.record(order, step="order_terminal", label="订单已取消", timestamp=ctx.timestamp)
            elif order.status is OrderStatus.EXPIRED:
                store.record(order, step="order_terminal", label="订单已过期", timestamp=ctx.timestamp)
            elif order.status is OrderStatus.FILLED:
                store.record(order, step="order_terminal", label="订单成交", timestamp=ctx.timestamp)
            else:
                store.record(
                    order,
                    step="order_working",
                    label="订单仍在场内",
                    timestamp=ctx.timestamp,
                    details={"next_status": order.status.value},
                )
