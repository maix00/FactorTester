"""Window and partition semantics for the public factor API."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class NanPolicy(str, Enum):
    PROPAGATE = "propagate"
    SKIP = "skip"


_UPSTREAM_MIN = {"var": 2, "std": 2, "skew": 3}


def default_min_periods(op: str, window: int) -> int:
    return min(max(1, window), _UPSTREAM_MIN.get(op.removeprefix("rolling_"), 1))


@dataclass(frozen=True, slots=True)
class WindowSemantics:
    window: int
    min_periods: int | None = None
    nan_policy: NanPolicy = NanPolicy.PROPAGATE

    def min_periods_for(self, op: str) -> int:
        return default_min_periods(op, self.window) if self.min_periods is None else self.min_periods


@dataclass(frozen=True, slots=True)
class PartitionSemantics:
    min_periods: int | None = 1
    nan_policy: NanPolicy = NanPolicy.PROPAGATE

    @property
    def effective_min_periods(self) -> int:
        return 1 if self.min_periods is None else self.min_periods
