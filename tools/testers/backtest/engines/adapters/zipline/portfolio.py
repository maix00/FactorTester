"""Portfolio intent bridge for Zipline target-order helpers."""

from __future__ import annotations

from collections.abc import Mapping


def apply_target_weights(
    algorithm: object,
    weights: Mapping[str, float],
    assets: Mapping[str, object],
) -> list[object]:
    if set(weights) != set(assets):
        raise ValueError("Zipline weights and assets must match")
    orders = []
    for instrument, target in weights.items():
        order = algorithm.order_target_percent(assets[instrument], float(target))
        if order is not None:
            orders.append(order)
    return orders
