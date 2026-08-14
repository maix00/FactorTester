"""Predictive IC half-life over a frozen horizon set."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

from tools.factors.tester_calc.single_factor_test.ic_half_life import (
    fit_forward_ic_half_life,
)


@dataclass(frozen=True, slots=True)
class ICForwardHorizonHalfLife:
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, **dict(self.payload)}


class ICForwardHorizonHalfLifeAdapter:
    analysis_type = "forward_horizon_half_life"
    input_kinds = ("ic_statistics",)
    output_kind = "forward_horizon_half_life"

    def execute(
        self,
        inputs: tuple[Mapping[str, Any], ...],
        parameters: Mapping[str, Any],
    ) -> ICForwardHorizonHalfLife:
        if len(inputs) < 2:
            raise ValueError("forward horizon half-life requires two horizons")
        points: list[tuple[float, str, float]] = []
        for item in inputs:
            stats = item.get("ic_statistics")
            if not isinstance(stats, Mapping):
                raise ValueError("half-life input must expose ic_statistics")
            seconds = stats.get("horizon_seconds")
            mean = stats.get("mean_ic")
            if not _finite_positive(seconds) or not _finite(mean):
                raise ValueError(
                    "half-life statistics require finite horizon_seconds and mean_ic"
                )
            points.append((float(seconds), str(stats.get("horizon") or seconds), float(mean)))
        points.sort(key=lambda item: item[0])
        return ICForwardHorizonHalfLife(fit_forward_ic_half_life(points))


def _finite(value: Any) -> bool:
    try:
        return isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _finite_positive(value: Any) -> bool:
    return _finite(value) and float(value) > 0


__all__ = ["ICForwardHorizonHalfLife", "ICForwardHorizonHalfLifeAdapter"]
