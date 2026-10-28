"""Resolved inclusive intervals consumed by the Rust interval kernel.

Window, scope, truncate and event boundaries all resolve to this one type
before arithmetic.  Boundaries themselves live in ``tools.factors.events``
and in the Rust ``IntervalSpec``; this is the runtime hand-off to the kernel.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IntervalSpec:
    start: int
    end: int

    def __post_init__(self) -> None:
        if not isinstance(self.start, int) or not isinstance(self.end, int):
            raise TypeError("interval boundaries must be integers")
        if self.start < 0 or self.end < self.start:
            raise ValueError("interval must satisfy 0 <= start <= end")

    @property
    def width(self) -> int:
        return self.end - self.start + 1
