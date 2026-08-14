"""Rolling IC stability over signal-count windows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class ICRollingWindowRow:
    requested_signal_count: int
    rolling_windows_count: int
    estimable: bool
    detail_status: str
    mean_ic_p10: float | None
    mean_ic_p50: float | None
    mean_ic_p90: float | None
    icir_p10: float | None
    icir_p50: float | None
    icir_p90: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_signal_count": self.requested_signal_count,
            "rolling_windows_count": self.rolling_windows_count,
            "estimable": self.estimable,
            "detail_status": self.detail_status,
            "mean_ic_p10": self.mean_ic_p10,
            "mean_ic_p50": self.mean_ic_p50,
            "mean_ic_p90": self.mean_ic_p90,
            "icir_p10": self.icir_p10,
            "icir_p50": self.icir_p50,
            "icir_p90": self.icir_p90,
        }


@dataclass(frozen=True, slots=True)
class ICRollingStatistics:
    rows: tuple[ICRollingWindowRow, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "window_unit": "signal_count",
            "rows": [row.to_dict() for row in self.rows],
        }


class ICRollingStabilityAdapter:
    analysis_type = "rolling_ic_stability"
    input_kinds = ("ic_series",)
    output_kind = "rolling_ic_statistics"

    def execute(
        self,
        inputs: tuple[Mapping[str, Any], ...],
        parameters: Mapping[str, Any],
    ) -> ICRollingStatistics:
        if len(inputs) != 1 or not isinstance(inputs[0]["ic_series"], pd.Series):
            raise ValueError("rolling IC stability requires one pandas IC series")
        values = _finite_values(inputs[0]["ic_series"])
        windows = parameters.get("rolling_windows")
        if not isinstance(windows, list) or not windows:
            raise ValueError("rolling_windows must be a non-empty frozen list")
        rows = tuple(_summarize(values, _window_size(item)) for item in windows)
        return ICRollingStatistics(rows)


def _finite_values(series: pd.Series) -> np.ndarray:
    values = series.replace([np.inf, -np.inf], np.nan).dropna()
    return values.to_numpy(dtype=float)


def _window_size(item: Any) -> int:
    if not isinstance(item, dict) or item.get("unit") != "signals":
        raise ValueError("rolling window must use the signal_count unit")
    value = item.get("value")
    if isinstance(value, bool) or not isinstance(value, int) or value < 2:
        raise ValueError("rolling signal window must be an integer >= 2")
    return value


def _summarize(values: np.ndarray, window: int) -> ICRollingWindowRow:
    count = max(0, values.size - window + 1)
    if not count:
        return ICRollingWindowRow(
            window, 0, False, "summary_only", *(None for _ in range(6)),
        )
    sums = np.cumsum(np.insert(values, 0, 0.0))
    means = (sums[window:] - sums[:-window]) / window
    squares = np.cumsum(np.insert(values * values, 0, 0.0))
    variance = np.maximum(
        0.0,
        (squares[window:] - squares[:-window] - window * means * means)
        / (window - 1),
    )
    std = np.sqrt(variance)
    with np.errstate(divide="ignore", invalid="ignore"):
        icir = np.divide(means, std, out=np.full_like(means, np.nan), where=std > 0)
    return ICRollingWindowRow(
        window,
        count,
        True,
        "summary_only",
        *_quantiles(means),
        *_quantiles(icir),
    )


def _quantiles(values: np.ndarray) -> tuple[float | None, float | None, float | None]:
    finite = values[np.isfinite(values)]
    if not finite.size:
        return None, None, None
    return tuple(round(float(np.quantile(finite, q)), 6) for q in (0.10, 0.50, 0.90))


__all__ = ["ICRollingStabilityAdapter", "ICRollingStatistics", "ICRollingWindowRow"]
