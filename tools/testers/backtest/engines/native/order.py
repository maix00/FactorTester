"""OrderStatus/Order — the order lifecycle. Cancelled/Accepted/Rejected/
Scheduled/Filled are OrderStatus values, not separate EventKinds; an
in-flight Order is mutated in place (the EventQueue holds a reference to
the same object), not replaced by a new event."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from tools.products.Product import Product
    from tools.testers.backtest.engines.native.strategy import Strategy


class OrderStatus(str, Enum):
    DRAFT = "draft"          # just instantiated by OrderBookModule.construct_orders
    SCHEDULED = "scheduled"  # SignalToOrderModule has set the expected fill timestamp
                              # and pushed an EventKind.ORDER event; waiting for it to fire
    CANCELLED = "cancelled"  # superseded by a newer signal before it fired
    ACCEPTED = "accepted"    # standoff chain ran, constraints satisfied
    REJECTED = "rejected"    # standoff chain ran, some constraint rejected it
    FILLED = "filled"        # accounted for (cash/positions updated)


@dataclass
class Order:
    instrument: "Product"     # Product, not a string — Product is a UniqueNameObject
                               # (hashable, usable as a dict key directly)
    timestamp: pd.Timestamp
    quantity: float
    intent_quantity: float    # pre-rounding/pre-liquidity-cap quantity, kept for diagnostics
    strategy: "Strategy"       # which strategy this Order belongs to — determines which
                               # Ledger it's accounted against
    status: OrderStatus = OrderStatus.DRAFT
    reject_reason: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)  # open annotation container,
                                                              # unrelated to any module's FieldRefs

    def get(self, key: str, default: Any = None) -> Any:
        return self.fields.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.fields[key] = value
