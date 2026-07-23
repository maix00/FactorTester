"""One atomic executable Order with cumulative fill projections."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pandas as pd

from .enums import (
    OrderEffect,
    OrderLegRole,
    OrderOffset,
    OrderSide,
    OrderStatus,
    TimeInForce,
)

if TYPE_CHECKING:
    from tools.products.Product import Product
    from tools.testers.backtest.engines.native.strategy import Strategy


@dataclass
class Order:
    instrument: "Product"
    timestamp: pd.Timestamp
    quantity: float
    intent_quantity: float
    strategy: "Strategy"
    status: OrderStatus = OrderStatus.DRAFT
    reject_reason: str | None = None
    order_id: str = ""
    fields: dict[str, Any] = field(default_factory=dict)
    requested_quantity: float | None = None
    accepted_quantity: float | None = None
    filled_quantity: float = 0.0
    parent_intent_id: str = ""
    order_group_id: str = ""
    leg_role: OrderLegRole = OrderLegRole.ATOMIC_NET
    offset: OrderOffset = OrderOffset.AUTO
    execution_effect: OrderEffect = OrderEffect.MIXED
    side: OrderSide | None = None
    time_in_force: TimeInForce = TimeInForce.GTC
    submitted_at: pd.Timestamp | None = None
    eligible_at: pd.Timestamp | None = None
    revision: int = 0

    def __post_init__(self) -> None:
        if self.requested_quantity is None:
            self.requested_quantity = abs(float(self.quantity))
        if self.requested_quantity < 0:
            raise ValueError("Order.requested_quantity must be non-negative")
        if self.accepted_quantity is None:
            self.accepted_quantity = self.requested_quantity
        if self.accepted_quantity < 0:
            raise ValueError("Order.accepted_quantity must be non-negative")
        if self.filled_quantity < 0:
            raise ValueError("Order.filled_quantity must be non-negative")
        if self.side is None:
            self.side = OrderSide.BUY if self.quantity >= 0 else OrderSide.SELL
        self.submitted_at = self.submitted_at or self.timestamp
        self.eligible_at = self.eligible_at or self.timestamp
        self.assert_quantity_invariant()

    @property
    def current_order_quantity(self) -> float:
        return float(self.accepted_quantity or 0.0)

    @property
    def unfilled_quantity(self) -> float:
        return max(self.current_order_quantity - self.filled_quantity, 0.0)

    @property
    def remaining_quantity(self) -> float:
        return 0.0 if self.status.terminal else self.unfilled_quantity

    @property
    def signed_remaining_quantity(self) -> float:
        sign = 1.0 if self.side is OrderSide.BUY else -1.0
        return sign * self.remaining_quantity

    def register_fill(self, quantity: float) -> None:
        if quantity <= 0:
            raise ValueError("registered fill quantity must be positive")
        if quantity > self.unfilled_quantity + 1e-12:
            raise ValueError("registered fill exceeds Order unfilled quantity")
        self.filled_quantity += quantity
        self.status = (
            OrderStatus.FILLED
            if self.unfilled_quantity <= 1e-12
            else OrderStatus.PARTIALLY_FILLED
        )
        self.assert_quantity_invariant()

    def assert_quantity_invariant(self) -> None:
        if self.filled_quantity > self.current_order_quantity + 1e-12:
            raise ValueError("Order filled quantity exceeds current order quantity")

    def get(self, key: str, default: Any = None) -> Any:
        return self.fields.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.fields[key] = value
