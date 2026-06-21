"""Portfolio intent bridge for Backtrader target-order helpers."""

from __future__ import annotations

from collections.abc import Mapping


def apply_target_weights(
    strategy: object,
    weights: Mapping[str, float],
    feeds: Mapping[str, object],
) -> list[object]:
    if set(weights) != set(feeds):
        raise ValueError("Backtrader weights and feeds must match")
    orders = []
    for instrument, target in weights.items():
        order = strategy.order_target_percent(data=feeds[instrument], target=float(target))
        if order is not None:
            orders.append(order)
    return orders
