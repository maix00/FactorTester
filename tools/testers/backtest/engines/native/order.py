"""Compatibility facade for the native order domain.

New code may import from ``native.orders``. Existing callers keep this stable
module while the lifecycle migration proceeds.
"""

from .orders import (
    Fill,
    FillSettlement,
    Order,
    OrderAction,
    OrderActionType,
    OrderAttempt,
    OrderEffect,
    OrderGroup,
    OrderLegRole,
    OrderOffset,
    OrderSide,
    OrderStatus,
    TimeInForce,
)

__all__ = [
    "Fill", "FillSettlement", "Order", "OrderAction", "OrderActionType",
    "OrderAttempt", "OrderEffect", "OrderGroup", "OrderLegRole", "OrderOffset",
    "OrderSide", "OrderStatus", "TimeInForce",
]
