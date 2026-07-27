"""Compatibility facade and executable module for order-flow audit."""

from __future__ import annotations

from typing import Any, ClassVar

from tools.testers.backtest.engines.native.fields import ExecutableModule
from tools.testers.backtest.modules.order_lifecycle import (
    OrderFlowStore,
    OrderStore,
    default_pending_order_conflict_policy,
    record_order_lifecycle_state,
)
from tools.testers.backtest.engines.native.fields import FieldRef


class OrderFlowModule(ExecutableModule):
    key: ClassVar[str] = "order_flow"
    label: ClassVar[str] = "订单流水"
    fields: ClassVar[dict[str, Any]] = {}
    status_events = FieldRef("status_events")
    flows: ClassVar[tuple[Any, ...]] = ()


def order_flow_store_for(state: Any) -> OrderFlowStore:
    return state.order_flow_store


def record_order_terminal_state(state: Any, ctx: Any) -> None:
    """Compatibility name; partial/working Orders are now valid outcomes."""
    record_order_lifecycle_state(state, ctx)


__all__ = [
    "OrderFlowModule",
    "OrderFlowStore",
    "OrderStore",
    "default_pending_order_conflict_policy",
    "order_flow_store_for",
    "record_order_terminal_state",
]
