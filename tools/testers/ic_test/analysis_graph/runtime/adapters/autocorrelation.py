"""Typed IC autocorrelation output over one core IC series."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class ICAutocorrelationRow:
    lag: int
    autocorrelation: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "lag": self.lag,
            "autocorrelation": self.autocorrelation,
        }


@dataclass(frozen=True, slots=True)
class ICAutocorrelationStatistics:
    n: int
    maximum_lag_requested: int
    maximum_lag_resolved: int
    rows: tuple[ICAutocorrelationRow, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "estimator": "direct_numpy_adjusted_false",
            "n": self.n,
            "maximum_lag_requested": self.maximum_lag_requested,
            "maximum_lag_resolved": self.maximum_lag_resolved,
            "rows": [row.to_dict() for row in self.rows],
        }


class ICAutocorrelationAdapter:
    analysis_type = "ic_autocorrelation"
    input_kinds = ("ic_series",)
    output_kind = "ic_autocorrelation"

    def execute(
        self,
        inputs: tuple[Mapping[str, Any], ...],
        parameters: Mapping[str, Any],
    ) -> ICAutocorrelationStatistics:
        if len(inputs) != 1 or not isinstance(inputs[0]["ic_series"], pd.Series):
            raise ValueError("IC autocorrelation requires one pandas IC series")
        requested = _maximum_lag(parameters.get("maximum_lag"))
        series = inputs[0]["ic_series"].dropna()
        values = series.to_numpy(dtype=float)
        if len(values) <= 2:
            return ICAutocorrelationStatistics(len(values), requested, 0, ())
        centered = values - float(values.mean())
        denominator = float(np.dot(centered, centered))
        if denominator <= 0:
            return ICAutocorrelationStatistics(len(values), requested, 0, ())
        resolved = min(requested, max(1, len(values) // 2 - 1))
        rows = tuple(
            ICAutocorrelationRow(
                lag,
                _round(float(np.dot(centered[lag:], centered[:-lag]) / denominator)),
            )
            for lag in range(1, resolved + 1)
        )
        return ICAutocorrelationStatistics(
            len(values), requested, resolved, rows,
        )


def _maximum_lag(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("maximum_lag must be a positive integer")
    return value


def _round(value: float) -> float:
    return round(float(value), 6)


__all__ = [
    "ICAutocorrelationAdapter",
    "ICAutocorrelationRow",
    "ICAutocorrelationStatistics",
]
