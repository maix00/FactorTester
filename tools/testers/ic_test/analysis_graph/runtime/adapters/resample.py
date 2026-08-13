"""IC resampling-stability adapter over effective IC observations."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any, Mapping

import pandas as pd


@dataclass(frozen=True, slots=True)
class ICResampleRow:
    sampling_interval: int
    mean: float | None
    std: float | None
    ir: float | None
    t_stat: float | None
    n: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "sampling_interval": self.sampling_interval,
            "mean": self.mean,
            "std": self.std,
            "ir": self.ir,
            "t_stat": self.t_stat,
            "n": self.n,
        }


@dataclass(frozen=True, slots=True)
class ICResampleStatistics:
    rows: tuple[ICResampleRow, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "sampling_unit": "effective_ic_observations",
            "rows": [row.to_dict() for row in self.rows],
        }


class ICResampleStabilityAdapter:
    analysis_type = "ic_resample_stability"
    input_kinds = ("ic_series",)
    output_kind = "ic_resample_statistics"

    def execute(
        self,
        inputs: tuple[Mapping[str, Any], ...],
        parameters: Mapping[str, Any],
    ) -> ICResampleStatistics:
        if len(inputs) != 1 or not isinstance(inputs[0]["ic_series"], pd.Series):
            raise ValueError("IC resample stability requires one pandas IC series")
        base = inputs[0]["ic_series"].dropna()
        intervals = parameters.get("sampling_intervals")
        if not isinstance(intervals, list):
            raise ValueError("sampling_intervals must be a frozen integer list")
        return ICResampleStatistics(tuple(
            _summarize(base.iloc[::interval], interval)
            for interval in intervals
        ))


def _summarize(series: pd.Series, interval: int) -> ICResampleRow:
    if len(series) <= 1:
        return ICResampleRow(interval, None, None, None, None, 0)
    mean = float(series.mean())
    std = float(series.std())
    n = len(series)
    return ICResampleRow(
        interval,
        _round(mean),
        _round(std),
        _round(mean / std) if std else None,
        _round(mean / (std / sqrt(n))) if std else None,
        n,
    )


def _round(value: float) -> float:
    return round(float(value), 6)


__all__ = [
    "ICResampleRow",
    "ICResampleStabilityAdapter",
    "ICResampleStatistics",
]
