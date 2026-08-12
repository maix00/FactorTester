"""Position cost-basis primitives."""

from __future__ import annotations

from collections import deque

from tools.testers.backtest.engines.native.order import OrderOffset
from tools.testers.backtest.engines.native.position import Lot, ProductPosition


def apply_lot_fill(
    entry: ProductPosition,
    method: str,
    quantity: float,
    price: float,
    multiplier: float,
    *,
    is_today: bool | None = None,
    offset: OrderOffset = OrderOffset.AUTO,
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
    raw = consume_lots(
        entry.lots, close_abs, price, multiplier, method=method, offset=offset,
    )
    realized = raw if prior_quantity > 0 else -raw
    flip_abs = abs(quantity) - close_abs
    if flip_abs > 1e-12:
        entry.lots.append(Lot(
            quantity=flip_abs * sign(quantity), entry_price=price,
            multiplier=multiplier, is_today=is_today,
        ))
    return realized


def consume_lots(
    lots, quantity: float, fill_price: float, multiplier: float, *,
    method: str, offset: OrderOffset,
) -> float:
    candidates = [
        lot for lot in ordered_lots(lots, method)
        if offset_matches(lot, offset)
    ]
    available = sum(abs(float(lot.quantity or 0.0)) for lot in candidates)
    if available + 1e-12 < quantity:
        raise ValueError(
            f"{offset.value} quantity {quantity} exceeds matching position lots {available}"
        )
    remaining = quantity
    realized = 0.0
    exhausted_ids: set[int] = set()
    for lot in candidates:
        if remaining <= 1e-12:
            break
        take = min(remaining, abs(float(lot.quantity)))
        realized += take * (fill_price - lot.entry_price) * multiplier
        lot.quantity -= take if lot.quantity > 0 else -take
        remaining -= take
        if abs(float(lot.quantity)) <= 1e-12:
            exhausted_ids.add(id(lot))
    if exhausted_ids:
        # Rebuild once after the simulation so consuming many lots does not
        # repeatedly scan the deque/list with remove().  Preserve the
        # original order for the surviving lots and support both the native
        # deque and compatibility list containers.
        survivors = [lot for lot in lots if id(lot) not in exhausted_ids]
        lots.clear()
        lots.extend(survivors)
    return realized


def ordered_lots(lots, method: str):
    if method == "LIFO":
        return list(reversed(lots))
    if method == "HIFO":
        return sorted(lots, key=lambda lot: lot.entry_price, reverse=True)
    return list(lots)


def offset_matches(lot, offset: OrderOffset) -> bool:
    if offset is OrderOffset.CLOSE_TODAY:
        return getattr(lot, "is_today", None) is True
    if offset is OrderOffset.CLOSE_YESTERDAY:
        return getattr(lot, "is_today", None) is False
    return True


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
