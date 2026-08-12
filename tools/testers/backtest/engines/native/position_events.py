"""Immutable position transitions emitted after a fill is posted to a ledger."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class PositionEventKind(str, Enum):
    OPENED = "opened"
    CHANGED = "changed"
    CLOSED = "closed"


@dataclass(frozen=True)
class PositionEvent:
    """A strategy-visible position transition, not a mutable ledger record."""

    kind: PositionEventKind
    product: Any
    previous_quantity: float
    quantity: float
    delta: float
    price: float
    order_id: str
    fill_id: str
    ledger_id: str


def position_events_for_fill(
    *,
    product: Any,
    previous_quantity: float,
    quantity: float,
    price: float,
    order_id: str,
    fill_id: str,
    ledger_id: str,
) -> tuple[PositionEvent, ...]:
    """Build the smallest causal transition sequence for one fill.

    A sign flip is represented as close-then-open, matching exchange position
    semantics instead of hiding two lifecycle transitions inside ``changed``.
    """

    if abs(previous_quantity) <= 1e-12 and abs(quantity) <= 1e-12:
        return ()
    common = dict(
        product=product,
        price=float(price),
        order_id=str(order_id),
        fill_id=str(fill_id),
        ledger_id=str(ledger_id),
    )
    if abs(previous_quantity) <= 1e-12:
        return (PositionEvent(
            PositionEventKind.OPENED, previous_quantity=0.0,
            quantity=quantity, delta=quantity, **common,
        ),)
    if abs(quantity) <= 1e-12:
        return (PositionEvent(
            PositionEventKind.CLOSED, previous_quantity=previous_quantity,
            quantity=0.0, delta=-previous_quantity, **common,
        ),)
    if previous_quantity * quantity < 0:
        return (
            PositionEvent(
                PositionEventKind.CLOSED, previous_quantity=previous_quantity,
                quantity=0.0, delta=-previous_quantity, **common,
            ),
            PositionEvent(
                PositionEventKind.OPENED, previous_quantity=0.0,
                quantity=quantity, delta=quantity, **common,
            ),
        )
    return (PositionEvent(
        PositionEventKind.CHANGED, previous_quantity=previous_quantity,
        quantity=quantity, delta=quantity - previous_quantity, **common,
    ),)
