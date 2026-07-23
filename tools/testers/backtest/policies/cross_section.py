"""Pure, deterministic cross-sectional selection tools."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TypeVar

Item = TypeVar("Item")
Ranked = Sequence[tuple[Item, float]]


def screen_cross_section(
    values: Mapping[Item, float],
    predicate: Callable[[Item, float], bool],
) -> dict[Item, float]:
    return {item: value for item, value in values.items() if predicate(item, value)}


def rank_cross_section(
    values: Mapping[Item, float],
    *,
    descending: bool = True,
    tie_breaker: Callable[[Item], str] | None = None,
) -> tuple[tuple[Item, float], ...]:
    """Rank values with a stable secondary key independent of input order."""
    stable_key = tie_breaker or _item_name
    direction = -1.0 if descending else 1.0
    return tuple(sorted(values.items(), key=lambda pair: (direction * pair[1], stable_key(pair[0]))))


def select_rank_group(
    ranked: Ranked[Item],
    *,
    split_count: int,
    group_index: int,
) -> frozenset[Item]:
    """Select one rounded equal-count bucket from an already ranked section."""
    if split_count <= 0 or group_index < 0 or group_index >= split_count:
        return frozenset()
    bucket_size = len(ranked) / split_count
    start = round(group_index * bucket_size)
    end = round((group_index + 1) * bucket_size)
    return frozenset(item for item, _value in ranked[start:end])


def top(ranked: Ranked[Item], count: int) -> frozenset[Item]:
    return frozenset(item for item, _value in ranked[: max(0, count)])


def bottom(ranked: Ranked[Item], count: int) -> frozenset[Item]:
    if count <= 0:
        return frozenset()
    return frozenset(item for item, _value in ranked[-count:])


def _item_name(item: object) -> str:
    return str(getattr(item, "name", item))
