"""Infer fee close buckets for legacy AUTO/CLOSE Orders."""

from __future__ import annotations


def split_open_close_quantity(
    quantity: float, current_quantity: float,
) -> tuple[float, float]:
    if quantity == 0:
        return 0.0, 0.0
    if current_quantity == 0 or (quantity > 0) == (current_quantity > 0):
        return abs(quantity), 0.0
    close_qty = min(abs(quantity), abs(current_quantity))
    return max(0.0, abs(quantity) - close_qty), close_qty


def split_close_today_yesterday(
    quantity: float, position, close_qty: float,
    policy: str, cost_basis_method: str,
) -> tuple[float, float]:
    if close_qty <= 1e-12:
        return 0.0, 0.0
    if policy == "close_today":
        return close_qty, 0.0
    if policy == "close_yesterday":
        return 0.0, close_qty
    if policy not in {"auto", "custom", "exact"}:
        return 0.0, close_qty
    lots = getattr(position, "lots", None)
    if not lots:
        return 0.0, close_qty
    remaining = close_qty
    today = 0.0
    yesterday = 0.0
    for lot in ordered_lots_for_close(lots, cost_basis_method):
        if remaining <= 1e-12:
            break
        take = min(
            remaining, abs(float(getattr(lot, "quantity", 0.0) or 0.0)),
        )
        if bool(getattr(lot, "is_today", False)):
            today += take
        else:
            yesterday += take
        remaining -= take
    return today, yesterday + max(0.0, remaining)


def ordered_lots_for_close(lots, cost_basis_method: str):
    if cost_basis_method == "LIFO":
        return list(reversed(lots))
    if cost_basis_method == "HIFO":
        return sorted(
            lots, key=lambda lot: getattr(lot, "entry_price", 0.0), reverse=True,
        )
    return list(lots)
