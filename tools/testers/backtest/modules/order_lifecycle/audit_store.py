"""Structured, serializable order-flow audit records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tools.testers.backtest.engines.native.order import Order

from .values import float_or_none, timestamp_key


@dataclass
class OrderFlowStore:
    _next_id_by_strategy: dict[str, int] = field(default_factory=dict)
    records_by_strategy: dict[Any, list[dict[str, Any]]] = field(default_factory=dict)
    records_by_order: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def next_order_id(self, strategy: Any, timestamp: Any) -> str:
        alias = str(getattr(strategy, "alias", strategy))
        next_id = self._next_id_by_strategy.get(alias, 0) + 1
        self._next_id_by_strategy[alias] = next_id
        return f"{alias}-{timestamp_key(timestamp)}-{next_id}"

    def record(
        self,
        order: Order,
        *,
        step: str,
        label: str,
        timestamp: Any | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        order_id = _ensure_order_id(self, order, timestamp)
        record = {
            "order_id": order_id,
            "order_group_id": order.order_group_id,
            "parent_intent_id": order.parent_intent_id,
            "strategy_id": str(getattr(order.strategy, "alias", order.strategy)),
            "timestamp": timestamp_key(timestamp or order.timestamp),
            "step": step,
            "label": label,
            "product": str(getattr(order.instrument, "name", order.instrument)),
            "quantity": float(order.quantity or 0.0),
            "intent_quantity": float(order.intent_quantity or 0.0),
            "requested_quantity": float(order.requested_quantity or 0.0),
            "filled_quantity": float(order.filled_quantity),
            "remaining_quantity": float(order.remaining_quantity),
            "unfilled_quantity": float(order.unfilled_quantity),
            "status": order.status.value,
            "leg_role": order.leg_role.value,
            "offset": order.offset.value,
            "execution_effect": order.execution_effect.value,
            "revision": int(order.revision),
            "effective_price": float_or_none(order.get("effective_price")),
            "fee_cost": float_or_none(order.get("fee_cost")),
            "reject_reason": order.reject_reason or order.get("reject_reason"),
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
            "timestamp": timestamp_key(timestamp),
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


def _ensure_order_id(store: OrderFlowStore, order: Order, timestamp: Any) -> str:
    order_id = str(order.order_id or order.get("order_flow_id", "") or "")
    if order_id:
        return order_id
    order_id = store.next_order_id(order.strategy, timestamp or order.timestamp)
    order.order_id = order_id
    return order_id
