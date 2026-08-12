"""Order component helpers shared by cash and margin limits."""

from __future__ import annotations


def split_reducing_and_increasing(prior_quantity: float, order_quantity: float) -> tuple[float, float]:
    """Keep the full position-reducing component separate from new exposure."""
    if abs(order_quantity) <= 1e-12:
        return 0.0, 0.0
    if abs(prior_quantity) <= 1e-12 or prior_quantity * order_quantity > 0:
        return 0.0, order_quantity
    close_abs = min(abs(prior_quantity), abs(order_quantity))
    sign = 1.0 if order_quantity > 0 else -1.0
    reducing = sign * close_abs
    return reducing, order_quantity - reducing


def combine_preserving_reduction(reducing: float, increasing: float, scale: float) -> float:
    return reducing + increasing * max(0.0, min(1.0, float(scale)))
