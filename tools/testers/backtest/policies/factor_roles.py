"""Pure screen and sizing transforms for factor-role policies."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Literal, TypeVar

Item = TypeVar("Item")
ScreenRule = Literal["disabled", "gte", "lte", "between"]
SizingTransform = Literal["proportional", "inverse"]


def screen_ranking_values(
    ranking_values: Mapping[Item, float],
    screen_values: Mapping[Item, float],
    *,
    rule: ScreenRule,
    lower: float = 0.0,
    upper: float = 0.0,
) -> dict[Item, float]:
    """Apply a causal per-period eligibility screen before ranking."""
    if rule == "disabled":
        return dict(ranking_values)
    if rule == "between" and lower > upper:
        raise ValueError("screen_lower must be <= screen_upper")
    if rule not in {"gte", "lte", "between"}:
        raise ValueError(f"unsupported screen_rule: {rule}")

    def eligible(value: object) -> bool:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(number):
            return False
        if rule == "gte":
            return number >= lower
        if rule == "lte":
            return number <= upper
        return lower <= number <= upper

    return {
        item: value
        for item, value in ranking_values.items()
        if item in screen_values and eligible(screen_values[item])
    }


def factor_weight(
    items: Iterable[Item],
    values: Mapping[Item, float],
    *,
    transform: SizingTransform,
) -> dict[Item, float]:
    """Normalize positive finite sizing values over already selected items."""
    raw: dict[Item, float] = {}
    for item in items:
        try:
            value = float(values[item])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(value) or value <= 0:
            continue
        raw[item] = value if transform == "proportional" else 1.0 / value
    if transform not in {"proportional", "inverse"}:
        raise ValueError(f"unsupported sizing transform: {transform}")
    total = sum(raw.values())
    return {item: value / total for item, value in raw.items()} if total else {}
