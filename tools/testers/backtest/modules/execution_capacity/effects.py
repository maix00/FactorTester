"""Classify an atomic Order by its effect on the current net position."""

from __future__ import annotations

from typing import Any

from tools.testers.backtest.engines.native.order import OrderEffect, OrderSide
from tools.testers.backtest.modules.ledger_module import LedgerModule


def classify_order_effect(state: Any, order: Any) -> OrderEffect:
    if order.offset.value.startswith("close"):
        return OrderEffect.REDUCE
    if order.offset.value == "open":
        return OrderEffect.INCREASE
    positions = state.ledger_for(order).get(LedgerModule.positions, {})
    position = float(getattr(positions.get(order.instrument), "quantity", 0.0) or 0.0)
    leaves = float(order.remaining_quantity)
    if order.side is OrderSide.BUY and position < 0:
        return OrderEffect.REDUCE if leaves <= abs(position) + 1e-12 else OrderEffect.MIXED
    if order.side is OrderSide.SELL and position > 0:
        return OrderEffect.REDUCE if leaves <= abs(position) + 1e-12 else OrderEffect.MIXED
    return OrderEffect.INCREASE


def execution_priority(order: Any) -> tuple[int, Any, str]:
    rank = {
        OrderEffect.REDUCE: 0,
        OrderEffect.MIXED: 1,
        OrderEffect.INCREASE: 2,
    }[order.execution_effect]
    return rank, order.submitted_at, order.order_id
