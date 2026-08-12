from __future__ import annotations

from collections import defaultdict


def project_paired_intents(orders) -> list[dict]:
    by_parent = defaultdict(list)
    for order in orders:
        if order.parent_intent_id:
            by_parent[order.parent_intent_id].append(order)
    projections = []
    for parent_id, legs in sorted(by_parent.items()):
        products = {
            str(getattr(order.instrument, "name", order.instrument))
            for order in legs
        }
        if len(products) < 2:
            continue
        ratios = [_fill_ratio(order) for order in legs]
        spread = max(ratios) - min(ratios)
        projections.append({
            "parent_intent_id": parent_id,
            "execution_policy": _paired_policy(legs),
            "leg_count": len(legs),
            "products": sorted(products),
            "fill_ratios": ratios,
            "fill_ratio_spread": spread,
            "leg_exposure": spread > 1e-12,
            "status": "exposed" if spread > 1e-12 else "balanced",
        })
    return projections


def _fill_ratio(order) -> float:
    requested = float(order.current_order_quantity or 0.0)
    if requested <= 1e-12:
        return 1.0
    return min(float(order.filled_quantity or 0.0) / requested, 1.0)


def _paired_policy(orders) -> str | None:
    values = {
        order.get("paired_execution_policy")
        for order in orders
        if order.get("paired_execution_policy")
    }
    return next(iter(values)) if len(values) == 1 else None
