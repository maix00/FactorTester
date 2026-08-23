"""Immutable order attempts, actions, fills, and settlement facts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .enums import OrderActionType, OrderOffset, OrderSide


@dataclass(frozen=True)
class OrderAttempt:
    attempt_id: str
    order_id: str
    revision: int
    timestamp: pd.Timestamp
    market_timestamp: pd.Timestamp
    _order: Any = field(repr=False, compare=False)

    @property
    def order(self) -> Any:
        return self._order

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "type": "OrderAttempt",
            "attempt_id": self.attempt_id,
            "order_id": self.order_id,
            "revision": self.revision,
            "timestamp": self.timestamp,
            "market_timestamp": self.market_timestamp,
        }


@dataclass(frozen=True)
class OrderAction:
    request_id: str
    order_id: str
    action: OrderActionType
    submitted_at: pd.Timestamp
    revision: int
    previous_request_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class Fill:
    fill_id: str
    order_id: str
    attempt_id: str
    timestamp: pd.Timestamp
    quantity: float
    price: float
    side: OrderSide
    offset: OrderOffset
    fee: float = 0.0
    source_execution_id: str = ""

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("Fill.quantity must be positive; direction belongs to Fill.side")
        if self.price <= 0:
            raise ValueError("Fill.price must be positive")

    @property
    def signed_quantity(self) -> float:
        return self.quantity if self.side is OrderSide.BUY else -self.quantity


@dataclass(frozen=True)
class FillSettlement:
    fill_id: str
    realized_pnl: float
    fee: float
    cash_before: float
    cash_after: float
    margin_before: float
    margin_after: float
    account_id: str = ""
    cash_pool_id: str = ""
    account_currency: str = ""
    cash_pool_base_currency: str = ""
