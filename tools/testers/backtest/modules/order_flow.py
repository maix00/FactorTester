"""OrderFlowModule — structured order lifecycle audit trail.

Snapshot views answer "what did the portfolio look like at this event".
Order flow answers "how did each order move through sizing, constraints,
execution cost, ledger update, and final status".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, TYPE_CHECKING

import pandas as pd

from tools.testers.backtest.engines.native.fields import ExecutableModule
from tools.testers.backtest.engines.native.order import OrderStatus

if TYPE_CHECKING:
    from tools.testers.backtest.engines.native.order import Order


@dataclass
class OrderStore:
    pending_orders: dict[Any, Any] = field(default_factory=dict)


@dataclass
class OrderFlowStore:
    _next_id: int = 0
    records_by_strategy: dict[Any, list[dict[str, Any]]] = field(default_factory=dict)
    records_by_order: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def next_order_id(self, strategy: Any, timestamp: Any) -> str:
        self._next_id += 1
        alias = str(getattr(strategy, "alias", strategy))
        ts = _timestamp_key(timestamp)
        return f"{alias}-{ts}-{self._next_id}"

    def record(
        self,
        order: "Order",
        *,
        step: str,
        label: str,
        timestamp: Any | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        order_id = str(getattr(order, "order_id", "") or order.get("order_flow_id", "") or "")
        if not order_id:
            order_id = self.next_order_id(order.strategy, timestamp or order.timestamp)
            try:
                order.order_id = order_id
            except Exception:
                order.set("order_flow_id", order_id)
        record = {
            "order_id": order_id,
            "strategy_id": str(getattr(order.strategy, "alias", order.strategy)),
            "timestamp": _timestamp_key(timestamp or order.timestamp),
            "step": step,
            "label": label,
            "product": str(getattr(getattr(order, "instrument", None), "name", getattr(order, "instrument", ""))),
            "quantity": float(getattr(order, "quantity", 0.0) or 0.0),
            "intent_quantity": float(getattr(order, "intent_quantity", 0.0) or 0.0),
            "status": str(getattr(getattr(order, "status", None), "value", getattr(order, "status", ""))),
            "effective_price": _float_or_none(order.get("effective_price")),
            "fee_cost": _float_or_none(order.get("fee_cost")),
            "reject_reason": getattr(order, "reject_reason", None) or order.get("reject_reason"),
            "details": dict(details or {}),
        }
        self.records_by_order.setdefault(order_id, []).append(record)
        self.records_by_strategy.setdefault(order.strategy, []).append(record)

    def records_for_strategy(self, strategy: Any) -> list[dict[str, Any]]:
        return list(self.records_by_strategy.get(strategy, ()))

    def records_for_order(self, order_id: str) -> list[dict[str, Any]]:
        return list(self.records_by_order.get(str(order_id), ()))

    def record_strategy_step(
        self,
        strategy: Any,
        *,
        timestamp: Any,
        step: str,
        label: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.records_by_strategy.setdefault(strategy, []).append({
            "order_id": "",
            "strategy_id": str(getattr(strategy, "alias", strategy)),
            "timestamp": _timestamp_key(timestamp),
            "step": step,
            "label": label,
            "product": "",
            "quantity": None,
            "intent_quantity": None,
            "status": "",
            "effective_price": None,
            "fee_cost": None,
            "reject_reason": None,
            "details": dict(details or {}),
        })


class OrderFlowModule(ExecutableModule):
    key: ClassVar[str] = "order_flow"
    label: ClassVar[str] = "订单流水"
    fields: ClassVar[dict[str, Any]] = {}
    flows: ClassVar[tuple[Any, ...]] = ()


def default_pending_order_conflict_policy(
    state: Any,
    strategy: Any,
    order: Any,
    signal_timestamp: Any,
) -> None:
    """Default pending-order policy: latest signal replaces future work.

    It only cancels an existing order for the same strategy/product when that
    order's own scheduled execution timestamp is still in the future. An order
    due at the current signal boundary is already actionable and is left alone.
    """
    pending = state.order_store.pending_orders
    key = (strategy, order.instrument)
    stale = pending.get(key)
    if (
        stale is not None
        and stale.status == OrderStatus.SCHEDULED
        and stale.get("price_timestamp", stale.timestamp) > signal_timestamp
    ):
        stale.status = OrderStatus.CANCELLED


def order_flow_store_for(state: Any) -> OrderFlowStore:
    return state.order_flow_store


def record_order_terminal_state(state: Any, ctx: Any) -> None:
    """Record terminal order state after settlement/cancellation.

    This is deliberately a helper, not a standalone flow: FILLED/REJECTED are
    produced by the ledger settlement flow, while CANCELLED is produced by the
    scheduling/cancellation path. A separate lifecycle flow would split the
    order's status fact from the business action that created it.
    """
    store = order_flow_store_for(state)
    for strategy in ctx.active_strategies:
        for order in ctx.payloads_for(strategy):
            if order.status == OrderStatus.CANCELLED:
                store.record(order, step="order_terminal", label="订单已取消", timestamp=ctx.timestamp)
                continue
            if order.status == OrderStatus.REJECTED:
                store.record(
                    order,
                    step="order_terminal",
                    label="订单拒绝",
                    timestamp=ctx.timestamp,
                    details={"reject_reason": str(order.reject_reason or order.get("reject_reason") or "")},
                )
                continue
            if order.status == OrderStatus.FILLED:
                store.record(order, step="order_terminal", label="订单成交", timestamp=ctx.timestamp)
                continue
            raise RuntimeError(
                f"ORDER event for {order.instrument} finished without terminal status: {order.status}"
            )


def _timestamp_key(value: Any) -> str:
    if value is None:
        return ""
    return pd.Timestamp(value).isoformat()


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
