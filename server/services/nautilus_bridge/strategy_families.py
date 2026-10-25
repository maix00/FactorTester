"""Pure strategy-family decisions shared by Nautilus adapters.

Factor values are inputs to a strategy family, not the strategy itself.  These
functions only decide target membership/state; order execution stays in the
Nautilus Strategy adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Any


@dataclass(frozen=True, slots=True)
class CrossSectionalGroup:
    split_count: int
    group_index: int

    def __post_init__(self) -> None:
        if self.split_count < 2:
            raise ValueError("split_count must be >= 2")
        if not 1 <= self.group_index <= self.split_count:
            raise ValueError("group_index must be within split_count")

    def members(self, factor_values: Mapping[Any, float]) -> tuple[Any, ...]:
        if not factor_values:
            return ()
        ordered = sorted(
            factor_values.items(), key=lambda item: (float(item[1]), str(item[0])),
        )
        size = len(ordered)
        start = (self.group_index - 1) * size // self.split_count
        end = self.group_index * size // self.split_count
        return tuple(product for product, _ in ordered[start:end])


@dataclass(frozen=True, slots=True)
class ThresholdState:
    entry: float
    exit: float
    side_mode: str = "long_short"

    def __post_init__(self) -> None:
        if self.entry < 0 or self.exit < 0:
            raise ValueError("thresholds must be non-negative")
        if self.exit > self.entry:
            raise ValueError("exit threshold must not exceed entry threshold")
        if self.side_mode not in {"long_short", "long_only", "short_only"}:
            raise ValueError("invalid side_mode")

    def direction(self, value: float) -> int:
        if value >= self.entry:
            return 1 if self.side_mode != "short_only" else -1
        if value <= -self.entry:
            return -1 if self.side_mode != "long_only" else 1
        if abs(value) <= self.exit:
            return 0
        return 0
