"""Resolve close offsets from the position lots selected by cost basis."""

from __future__ import annotations

from tools.testers.backtest.engines.native.order import OrderLegRole, OrderOffset


def validate_exact_close_lots(position, close_quantity: float) -> None:
    lots = list(getattr(position, "lots", None) or ())
    available = sum(abs(float(lot.quantity or 0.0)) for lot in lots)
    if available + 1e-12 < close_quantity:
        raise ValueError(
            "exact order decomposition requires complete position lots "
            f"before closing {close_quantity}; available={available}"
        )
    if any(getattr(lot, "is_today", None) is None for lot in lots):
        raise ValueError(
            "exact order decomposition requires today/yesterday age "
            "for every closing lot"
        )


def close_buckets(position, close_quantity: float, method: str):
    lots = list(getattr(position, "lots", None) or ())
    if not lots:
        return [(OrderOffset.CLOSE, OrderLegRole.CLOSE, close_quantity)]
    if method == "LIFO":
        lots.reverse()
    elif method == "HIFO":
        lots.sort(key=lambda lot: float(lot.entry_price), reverse=True)
    quantities: dict[tuple[OrderOffset, OrderLegRole], float] = {}
    order: list[tuple[OrderOffset, OrderLegRole]] = []
    remaining = close_quantity
    for lot in lots:
        if remaining <= 1e-12:
            break
        quantity = min(remaining, abs(float(lot.quantity or 0.0)))
        key = offset_for_lot(lot)
        if key not in quantities:
            quantities[key] = 0.0
            order.append(key)
        quantities[key] += quantity
        remaining -= quantity
    if remaining > 1e-12:
        key = (OrderOffset.CLOSE, OrderLegRole.CLOSE)
        if key not in quantities:
            quantities[key] = 0.0
            order.append(key)
        quantities[key] += remaining
    return [(offset, role, quantities[(offset, role)]) for offset, role in order]


def offset_for_lot(lot):
    marker = getattr(lot, "is_today", None)
    if marker is True:
        return OrderOffset.CLOSE_TODAY, OrderLegRole.CLOSE_TODAY
    if marker is False:
        return OrderOffset.CLOSE_YESTERDAY, OrderLegRole.CLOSE_YESTERDAY
    return OrderOffset.CLOSE, OrderLegRole.CLOSE
