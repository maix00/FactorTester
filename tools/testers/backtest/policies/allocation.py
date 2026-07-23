"""Pure target-allocation tools."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal, TypeVar

Item = TypeVar("Item")
MissingMeasurePolicy = Literal["equal_share", "exclude"]


def equal_weight(items: Iterable[Item]) -> dict[Item, float]:
    selected = tuple(items)
    if not selected:
        return {}
    weight = 1.0 / len(selected)
    return {item: weight for item in selected}


def inverse_measure_weight(
    items: Iterable[Item],
    measures: Mapping[Item, float],
    *,
    missing: MissingMeasurePolicy = "equal_share",
) -> dict[Item, float]:
    """Normalize inverse positive measures without inventing missing data."""
    selected = tuple(items)
    if not selected:
        return {}
    inverse = {
        item: 1.0 / float(measures[item])
        for item in selected
        if item in measures and float(measures[item]) > 0
    }
    if not inverse:
        return equal_weight(selected)

    missing_items = tuple(item for item in selected if item not in inverse)
    missing_share = len(missing_items) / len(selected) if missing == "equal_share" else 0.0
    available_share = 1.0 - missing_share
    total_inverse = sum(inverse.values())
    weights = {item: available_share * value / total_inverse for item, value in inverse.items()}
    if missing == "equal_share":
        weights.update({item: 1.0 / len(selected) for item in missing_items})
    return weights
