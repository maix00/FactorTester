"""Position cost-basis primitives."""

from __future__ import annotations

from collections import deque

from tools.testers.backtest.engines.native.position import Lot, ProductPosition
from tools.testers.backtest.modules.trading_rule import _consume_lots, _consume_lots_hifo


def apply_lot_fill(
    entry: ProductPosition,
    method: str,
    quantity: float,
    price: float,
    multiplier: float,
    *,
    is_today: bool | None = None,
) -> float:
    """Apply a fill to FIFO/LIFO/HIFO lots and return realized P&L."""
    if entry.lots is None:
        entry.lots = deque()
    prior_quantity = float(entry.quantity or 0.0)
    if prior_quantity == 0 or same_direction(prior_quantity, quantity):
        entry.lots.append(Lot(
            quantity=quantity, entry_price=price,
            multiplier=multiplier, is_today=is_today,
        ))
        return 0.0
    close_abs = min(abs(quantity), abs(prior_quantity))
    if method == "FIFO":
        raw = _consume_lots(entry.lots, close_abs, price, multiplier, from_front=True)
    elif method == "LIFO":
        raw = _consume_lots(entry.lots, close_abs, price, multiplier, from_front=False)
    else:
        raw = _consume_lots_hifo(entry.lots, close_abs, price, multiplier)
    realized = raw if prior_quantity > 0 else -raw
    flip_abs = abs(quantity) - close_abs
    if flip_abs > 1e-12:
        entry.lots.append(Lot(
            quantity=flip_abs * sign(quantity), entry_price=price,
            multiplier=multiplier, is_today=is_today,
        ))
    return realized


def weighted_average_cost(
    prior_quantity: float, prior_cost: float, quantity: float, price: float,
) -> float:
    total = abs(prior_quantity) + abs(quantity)
    if total <= 1e-12:
        return 0.0
    return (abs(prior_quantity) * prior_cost + abs(quantity) * price) / total


def same_direction(left: float, right: float) -> bool:
    return (left >= 0 and right >= 0) or (left <= 0 and right <= 0)


def sign(value: float) -> float:
    return 1.0 if value >= 0 else -1.0
