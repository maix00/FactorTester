"""DataMoney — a currency-aware amount type with arithmetic operators,
replacing DataMoneyMinorUnits in Flow-typed fields. amount can be a numpy
array (vectorized across strategies/instruments), not just a scalar.
DataMoneyMinorUnits (currency_units.py) stays as a plain storage container
and is unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .currency_units import major_to_minor_units, minor_units_to_major


@dataclass(frozen=True)
class DataMoney:
    amount: Any        # np.ndarray | float — integer minor units if use_minor_units,
                         # else major-unit float
    currency: str
    use_minor_units: bool
    scale: int = 100

    @classmethod
    def from_major(
        cls, value: Any, *, currency: str, use_minor_units: bool, scale: int = 100,
    ) -> "DataMoney":
        if use_minor_units:
            return cls(major_to_minor_units(value, scale=scale), currency, True, scale)
        return cls(np.asarray(value, dtype=float), currency, False, scale)

    def to_major(self) -> Any:
        if self.use_minor_units:
            return minor_units_to_major(self.amount, scale=self.scale)
        return self.amount

    def _check_compatible(self, other: "DataMoney") -> None:
        if (self.currency, self.use_minor_units, self.scale) != (
            other.currency, other.use_minor_units, other.scale,
        ):
            raise ValueError(f"incompatible DataMoney: {self!r} vs {other!r}")

    def __add__(self, other: "DataMoney") -> "DataMoney":
        self._check_compatible(other)
        return DataMoney(self.amount + other.amount, self.currency, self.use_minor_units, self.scale)

    def __sub__(self, other: "DataMoney") -> "DataMoney":
        self._check_compatible(other)
        return DataMoney(self.amount - other.amount, self.currency, self.use_minor_units, self.scale)

    def __mul__(self, rate: Any) -> "DataMoney":
        # rate is a dimensionless ratio (fee rate, margin ratio, ...), not another DataMoney.
        # In minor-unit mode this rounds to the minor unit on every call (via
        # from_major) -- fine for a single scaling, but chaining several
        # DataMoney multiplications rounds once per step instead of once at
        # the final amount. Production accounting code deliberately avoids
        # this: it composes the underlying float arithmetic first and wraps
        # the final result in one DataMoney.from_major call (the "aggregate"
        # convention -- see trading_rule._money_calculation_policy).
        if self.use_minor_units:
            return DataMoney.from_major(
                self.to_major() * rate, currency=self.currency,
                use_minor_units=True, scale=self.scale,
            )
        return DataMoney(self.amount * np.asarray(rate, dtype=float), self.currency, False, self.scale)

    def __truediv__(self, divisor: Any) -> "DataMoney":
        return self.__mul__(1.0 / np.asarray(divisor, dtype=float))
