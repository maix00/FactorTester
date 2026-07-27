"""Stable vocabulary for exchange-style order lifecycle records."""

from __future__ import annotations

from enum import Enum


class OrderStatus(str, Enum):
    DRAFT = "draft"
    BLOCKED = "blocked"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    CANCEL_PENDING = "cancel_pending"
    REPLACE_PENDING = "replace_pending"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FILLED = "filled"
    EXPIRED = "expired"

    @property
    def terminal(self) -> bool:
        return self in {
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.FILLED,
            OrderStatus.EXPIRED,
        }


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderOffset(str, Enum):
    """Exchange offset carried by one atomic Order.

    ``AUTO`` is limited to the legacy atomic-net approximation.
    """

    AUTO = "auto"
    OPEN = "open"
    CLOSE = "close"
    CLOSE_TODAY = "close_today"
    CLOSE_YESTERDAY = "close_yesterday"


class OrderEffect(str, Enum):
    REDUCE = "reduce"
    INCREASE = "increase"
    MIXED = "mixed"


class OrderLegRole(str, Enum):
    ATOMIC_NET = "atomic_net"
    CLOSE_TODAY = "close_today"
    CLOSE_YESTERDAY = "close_yesterday"
    CLOSE = "close"
    OPEN = "open"


class TimeInForce(str, Enum):
    GTC = "gtc"
    DAY = "day"
    IOC = "ioc"


class OrderActionType(str, Enum):
    SUBMIT = "submit"
    CANCEL = "cancel"
    REPLACE = "replace"
