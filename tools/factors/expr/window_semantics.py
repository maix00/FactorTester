"""Explicit rolling-window semantics.

Historically FactorExpr inherited two implicit rules from pandas:

* ``min_periods = window // 2`` for mean/std/var/skew (but 1 for sum/min/max)
* the current NaN bar is skipped and the previous aggregate is carried forward

Those rules are not part of the upstream Rust algorithms.  This module makes
both choices explicit so batch, streaming and factor serialization can agree.
The default follows upstream: a full window is required and any NaN inside the
window propagates to the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class NanPolicy(str, Enum):
    PROPAGATE = "propagate"
    SKIP = "skip"


# Upstream ta_ma/ta_sum/ta_stddev default: full window, NaN propagates.
DEFAULT_MIN_PERIODS: int | None = None  # None means "the whole window"
DEFAULT_NAN_POLICY = NanPolicy.PROPAGATE


@dataclass(frozen=True, slots=True)
class WindowSemantics:
    window: int
    min_periods: int | None = DEFAULT_MIN_PERIODS
    nan_policy: NanPolicy = DEFAULT_NAN_POLICY

    def __post_init__(self) -> None:
        if self.window < 1:
            raise ValueError("window must be positive")
        if self.min_periods is not None and not 1 <= self.min_periods <= self.window:
            raise ValueError("min_periods must be within [1, window]")

    @property
    def effective_min_periods(self) -> int:
        return self.window if self.min_periods is None else self.min_periods

    @property
    def propagate_nan(self) -> bool:
        return self.nan_policy is NanPolicy.PROPAGATE
