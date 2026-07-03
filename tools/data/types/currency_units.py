"""Currency-neutral integer minor-unit money helpers.

Amounts are provided in a currency's major unit (for example 1.23 in whatever
currency is active) and stored as integer minor units using a configurable
scale. Rates remain ratios; quantities remain in product units.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


DEFAULT_MINOR_UNIT_SCALE = 100


def major_to_minor_units(value: Any, *, scale: int = DEFAULT_MINOR_UNIT_SCALE) -> np.ndarray:
    """Round major-unit amount(s) half-up away from zero to integer minor units."""
    arr = np.asarray(value, dtype=float)
    arr = np.where(np.isfinite(arr), arr, 0.0)
    scaled = arr * int(scale)
    return (np.sign(scaled) * np.floor(np.abs(scaled) + 0.5 + 1e-9)).astype(np.int64)


def major_floor_to_minor_units(value: Any, *, scale: int = DEFAULT_MINOR_UNIT_SCALE) -> np.ndarray:
    """Floor major-unit amount(s) to nonnegative integer minor units."""
    arr = np.asarray(value, dtype=float)
    arr = np.where(np.isfinite(arr), arr, 0.0)
    return np.maximum(0, np.floor(arr * int(scale) + 1e-9).astype(np.int64))


def minor_units_to_major(minor_units: Any, *, scale: int = DEFAULT_MINOR_UNIT_SCALE) -> np.ndarray:
    return np.asarray(minor_units, dtype=float) / float(scale)


@dataclass(frozen=True)
class DataMoneyMinorUnits:
    minor_units: int
    currency: str = ""
    scale: int = DEFAULT_MINOR_UNIT_SCALE

    @classmethod
    def from_major(cls, value: Any, *, currency: str = "", scale: int = DEFAULT_MINOR_UNIT_SCALE) -> "DataMoneyMinorUnits":
        return cls(int(major_to_minor_units(value, scale=scale)), currency=currency, scale=scale)

    @classmethod
    def floor_major(cls, value: Any, *, currency: str = "", scale: int = DEFAULT_MINOR_UNIT_SCALE) -> "DataMoneyMinorUnits":
        return cls(int(major_floor_to_minor_units(value, scale=scale)), currency=currency, scale=scale)

    def to_major(self) -> float:
        return float(self.minor_units) / float(self.scale)
