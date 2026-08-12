"""Validated opt-in performance profiling for one native backtest run."""

from __future__ import annotations

from typing import Any

from .profiling import BacktestProfiler, CumulativeBacktestProfiler


def normalize_performance_profile(value: Any) -> dict[str, Any] | None:
    if value is None or value is False:
        return None
    if not isinstance(value, dict):
        raise ValueError("performance_profile must be an object")
    kind = str(value.get("kind") or "").strip()
    if kind != "cumulative_flow":
        raise ValueError("performance_profile.kind must be cumulative_flow")
    raw_minimum = value.get("min_total_ms", 1000.0)
    if isinstance(raw_minimum, bool):
        raise ValueError("performance_profile.min_total_ms must be non-negative")
    try:
        minimum = float(raw_minimum)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "performance_profile.min_total_ms must be non-negative"
        ) from exc
    if minimum < 0:
        raise ValueError("performance_profile.min_total_ms must be non-negative")
    return {"kind": kind, "min_total_ms": minimum}


def build_backtest_profiler(value: Any) -> BacktestProfiler | None:
    normalized = normalize_performance_profile(value)
    if normalized is None:
        return None
    return CumulativeBacktestProfiler(
        min_duration_ms=float(normalized["min_total_ms"]),
    )
