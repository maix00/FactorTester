"""Calendar-period diagnostics over one core IC series."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class ICPeriodRow:
    period_start: str
    period_estimable: bool
    n: int
    mean_ic: float | None
    std_ic: float | None
    ir: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_start": self.period_start,
            "period_estimable": self.period_estimable,
            "n": self.n,
            "mean_ic": self.mean_ic,
            "std_ic": self.std_ic,
            "ir": self.ir,
        }


@dataclass(frozen=True, slots=True)
class ICPeriodDiagnostics:
    periods: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, "periods": self.periods}


class ICPeriodDiagnosticsAdapter:
    analysis_type = "period_diagnostics"
    input_kinds = ("ic_series",)
    output_kind = "ic_period_diagnostics"

    def execute(
        self,
        inputs: tuple[Mapping[str, Any], ...],
        parameters: Mapping[str, Any],
    ) -> ICPeriodDiagnostics:
        if len(inputs) != 1 or not isinstance(inputs[0]["ic_series"], pd.Series):
            raise ValueError("period diagnostics requires one pandas IC series")
        raw_specs = parameters.get("periods")
        if not isinstance(raw_specs, list):
            raise ValueError("periods must be a frozen list")
        series = inputs[0]["ic_series"].replace([np.inf, -np.inf], np.nan).dropna()
        timestamps = _timestamps(series.index)
        result: dict[str, dict[str, Any]] = {}
        for spec in raw_specs:
            label, rule, min_signals, min_periods = _spec(spec)
            rows = _rows(series.to_numpy(dtype=float), timestamps, rule, min_signals)
            estimable = sum(item.period_estimable for item in rows)
            result[label] = {
                "rule": rule,
                "min_signal_observations": min_signals,
                "min_periods": min_periods,
                "n_periods_total": len(rows),
                "n_periods_estimable": estimable,
                "period_estimability_status": (
                    "estimable" if estimable >= min_periods else "not_estimable"
                ),
                "rows": [item.to_dict() for item in rows],
            }
        return ICPeriodDiagnostics(result)


def _timestamps(index: pd.Index) -> pd.DatetimeIndex:
    if isinstance(index, pd.MultiIndex):
        name = next(
            (item for item in index.names if item and str(item).startswith("_SIGNAL")),
            None,
        )
        return pd.DatetimeIndex(index.get_level_values(name or -1))
    return pd.DatetimeIndex(index)


def _spec(value: Any) -> tuple[str, str, int, int]:
    if not isinstance(value, dict):
        raise ValueError("period specification must be an object")
    rule = str(value.get("rule") or value.get("label") or "").strip().lower()
    if rule not in {"hour", "day", "week", "month", "quarter"}:
        raise ValueError(f"unsupported period rule: {rule}")
    label = str(value.get("label") or rule).strip()
    min_signals = _positive_int(value.get("min_signal_observations", 2), "min_signal_observations")
    min_periods = _positive_int(value.get("min_periods", 3), "min_periods")
    return label, rule, min_signals, min_periods


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _period_keys(timestamps: pd.DatetimeIndex, rule: str) -> pd.DatetimeIndex:
    if rule == "hour":
        return timestamps.floor("h")
    if rule == "day":
        return timestamps.normalize()
    if rule == "week":
        return timestamps.to_period("W").start_time
    if rule == "month":
        return timestamps.to_period("M").start_time
    return timestamps.to_period("Q").start_time


def _rows(values: np.ndarray, timestamps: pd.DatetimeIndex, rule: str, minimum: int) -> tuple[ICPeriodRow, ...]:
    keys = _period_keys(timestamps, rule)
    if not keys.is_monotonic_increasing:
        order = np.argsort(keys.asi8, kind="stable")
        keys, values = keys.take(order), values[order]
    boundaries = np.flatnonzero(keys.asi8[1:] != keys.asi8[:-1]) + 1
    starts = np.concatenate((np.array([0]), boundaries))
    ends = np.concatenate((boundaries, np.array([len(values)])))
    rows: list[ICPeriodRow] = []
    for start, end in zip(starts, ends):
        window = values[int(start):int(end)]
        n = int(window.size)
        mean = float(window.mean()) if n else None
        std = float(window.std(ddof=1)) if n > 1 else None
        rows.append(ICPeriodRow(
            keys[int(start)].isoformat(), n >= minimum, n,
            _round(mean), _round(std), _round(mean / std) if std else None,
        ))
    return tuple(rows)


def _round(value: float | None) -> float | None:
    return round(float(value), 6) if value is not None and np.isfinite(value) else None


__all__ = ["ICPeriodDiagnostics", "ICPeriodDiagnosticsAdapter", "ICPeriodRow"]
