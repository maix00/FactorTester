"""Frozen strategy-family configuration. Decisions execute only in Rust."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CrossSectionalGroup:
    split_count: int
    group_index: int

    def __post_init__(self) -> None:
        if self.split_count < 2:
            raise ValueError("split_count must be >= 2")
        if not 1 <= self.group_index <= self.split_count:
            raise ValueError("group_index must be within split_count")



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
