"""Typed values returned by independently replaceable market-rule providers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ContractRule:
    multiplier: float
    lot_size: float
    min_tick: float

    def __post_init__(self) -> None:
        if self.multiplier <= 0 or self.lot_size <= 0 or self.min_tick <= 0:
            raise ValueError("contract multiplier, lot size, and tick must be positive")


@dataclass(frozen=True, slots=True)
class FeeSchedule:
    notional_rate: float = 0.0
    fixed_minor_per_unit: int = 0

    def __post_init__(self) -> None:
        if self.notional_rate < 0 or self.fixed_minor_per_unit < 0:
            raise ValueError("fee schedule values must be non-negative")
