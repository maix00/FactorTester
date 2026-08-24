"""Fast, explicitly named half-life estimators for IC diagnostics.

The two estimators in this module answer different questions:

* ``fit_forward_ic_half_life`` fits an exponential curve to already computed
  forward-horizon IC means.  It is a predictive-decay estimate and requires
  no additional factor evaluation.
* ``fit_ic_series_ar1_half_life`` fits an AR(1) model to the realised IC
  sequence.  It measures persistence of successive IC observations, not the
  factor's forward-return holding horizon.

Neither result is called a ground-truth half-life.  The returned status makes
non-decay, sign reversal, and insufficient horizons explicit.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np

from .ic_decay_models import select_forward_ic_decay_model


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def fit_forward_ic_half_life(
    points: Iterable[tuple[float, str, float]],
    *,
    entry_delay_bars: int | None = None,
    baseline_seconds: float | None = None,
) -> dict[str, Any]:
    """Estimate predictive IC decay from ``(seconds, label, mean_ic)`` points.

    The baseline sign orients the curve.  All oriented means must remain
    strictly positive; a sign reversal is a failure state, not an absolute-
    value transformation.  For positive points we fit
    ``log(oriented_mean_ic) = intercept + slope * seconds`` and return
    ``log(0.5) / slope`` only when the fitted slope is negative.
    """

    clean: list[tuple[float, str, float]] = []
    for seconds, label, mean in points:
        seconds_value = _finite_float(seconds)
        mean_value = _finite_float(mean)
        if seconds_value is None or mean_value is None or seconds_value <= 0:
            continue
        clean.append((seconds_value, str(label), mean_value))
    clean.sort(key=lambda item: item[0])
    result: dict[str, Any] = {
        "method": "log_linear_ols",
        "entry_delay_bars": entry_delay_bars,
        "n_horizons": len(clean),
    }
    model_selection = select_forward_ic_decay_model(clean)
    result.update(model_selection)
    if len(clean) < 3:
        result["status"] = "insufficient_horizons"
        if clean:
            baseline_seconds, baseline_horizon, baseline_mean = clean[0]
            result.update({
                "baseline_horizon": baseline_horizon,
                "baseline_seconds": baseline_seconds,
                "baseline_mean_ic": baseline_mean,
                "expected_direction": int(1.0 if baseline_mean > 0 else -1.0) if baseline_mean != 0 else None,
                "last_horizon": clean[-1][1],
            })
        return result

    if baseline_seconds is not None:
        matching = [item for item in clean if abs(item[0] - float(baseline_seconds)) <= 1e-6]
        if not matching:
            result.update({
                "status": "baseline_horizon_not_observed",
                "baseline_seconds": float(baseline_seconds),
                "baseline_horizon": None,
                "expected_direction": None,
                "last_horizon": clean[-1][1],
            })
            return result
        baseline_seconds, baseline_horizon, baseline_mean = matching[0]
    else:
        baseline_seconds, baseline_horizon, baseline_mean = clean[0]
    if abs(baseline_mean) <= 1e-12:
        result.update({
            "status": "zero_baseline_ic",
            "baseline_horizon": baseline_horizon,
            "baseline_seconds": baseline_seconds,
            "baseline_mean_ic": baseline_mean,
            "expected_direction": None,
            "last_horizon": clean[-1][1],
        })
        return result

    direction = 1.0 if baseline_mean > 0 else -1.0
    oriented = [direction * item[2] for item in clean]
    invalid_indices = [index for index, value in enumerate(oriented) if value <= 1e-12]
    if invalid_indices:
        first_bad = invalid_indices[0]
        result.update({
            "status": "nonpositive_or_sign_reversal",
            "baseline_horizon": baseline_horizon,
            "baseline_seconds": baseline_seconds,
            "baseline_mean_ic": baseline_mean,
            "expected_direction": int(direction),
            "n_invalid_oriented_points": len(invalid_indices),
            "first_invalid_horizon": clean[first_bad][1],
            "last_horizon": clean[-1][1],
        })
        return result

    x = np.asarray([item[0] for item in clean], dtype=float)
    y = np.log(np.asarray(oriented, dtype=float))
    monotonic = all(
        later <= earlier + 1e-12
        for earlier, later in zip(oriented, oriented[1:])
    )
    if np.ptp(x) <= 0:
        result.update({
            "status": "degenerate_horizon_grid",
            "baseline_horizon": baseline_horizon,
            "baseline_seconds": baseline_seconds,
            "baseline_mean_ic": baseline_mean,
            "expected_direction": int(direction),
            "n_invalid_oriented_points": 0,
            "last_horizon": clean[-1][1],
            "curve_monotonic_nonincreasing": monotonic,
        })
        return result
    slope, intercept = np.polyfit(x, y, 1)
    fitted = intercept + slope * x
    residual_sum = float(np.sum((y - fitted) ** 2))
    total_sum = float(np.sum((y - float(np.mean(y))) ** 2))
    r_squared = 1.0 - residual_sum / total_sum if total_sum > 0 else 1.0
    result.update({
        "baseline_horizon": baseline_horizon,
        "baseline_seconds": baseline_seconds,
        "baseline_mean_ic": baseline_mean,
        "expected_direction": int(direction),
        "n_invalid_oriented_points": 0,
        "last_horizon": clean[-1][1],
        "curve_monotonic_nonincreasing": monotonic,
        "log_decay_slope_per_second": float(slope),
        "log_decay_intercept": float(intercept),
        "r_squared": float(r_squared),
        "log_fit_rmse": float(math.sqrt(residual_sum / len(clean))),
    })
    if not math.isfinite(float(slope)) or slope >= -1e-15:
        result["status"] = "not_decaying"
        return result
    half_life_seconds = math.log(0.5) / float(slope)
    result.update({
        "status": "estimated",
        "half_life_seconds": float(half_life_seconds),
    })
    return result


def evaluate_forward_ic_decay_curve(
    fitted: dict[str, Any],
    *,
    minimum_seconds: float,
    maximum_seconds: float,
    point_count: int = 201,
) -> list[dict[str, float]]:
    """Evaluate the selected forward-IC model on one canonical time grid.

    The returned values use the same direction-aligned axis as the fitter.
    Report SVGs and interactive clients consume these points directly so the
    model formula has exactly one implementation.
    """

    start = _finite_float(minimum_seconds)
    stop = _finite_float(maximum_seconds)
    count = max(2, int(point_count))
    if start is None or stop is None or stop < start:
        return []
    grid = np.linspace(start, stop, count)
    selected = str(fitted.get("selected_model") or "")
    if selected == "damped_oscillatory_exponential":
        smooth = fitted.get("smooth_fit")
        if not isinstance(smooth, dict):
            return []
        values = [
            _finite_float(smooth.get(key))
            for key in (
                "amplitude", "decay_per_day", "frequency_per_day",
                "phase", "offset",
            )
        ]
        if any(value is None for value in values):
            return []
        amplitude, decay, frequency, phase, offset = values
        elapsed_days = (grid - start) / 86400.0
        curve = (
            amplitude * np.exp(-decay * elapsed_days)
            * np.cos(frequency * elapsed_days + phase) + offset
        )
    elif selected == "exponential":
        slope = _finite_float(fitted.get("log_decay_slope_per_second"))
        intercept = _finite_float(fitted.get("log_decay_intercept"))
        if slope is None or intercept is None or slope >= 0:
            return []
        curve = np.exp(intercept + slope * grid)
    else:
        return []
    return [
        {"horizon_seconds": float(seconds), "oriented_mean_ic": float(value)}
        for seconds, value in zip(grid, curve)
        if math.isfinite(float(value))
    ]


def fit_ic_series_ar1_half_life(
    values: Iterable[Any],
    *,
    signal_interval_seconds: float | None = None,
) -> dict[str, Any]:
    """Estimate persistence half-life from an IC sequence using an AR(1) fit."""

    # IC diagnostics pass a finite NumPy array for long intraday sequences.
    # Keep that representation instead of iterating every observation through
    # Python ``float`` conversion; the old list materialisation was a second
    # full copy of hundreds of thousands of values for every horizon/delay.
    try:
        array = np.asarray(values, dtype=float)
    except (TypeError, ValueError):
        array = np.asarray(
            [number for value in values if (number := _finite_float(value)) is not None],
            dtype=float,
        )
    if array.ndim != 1:
        array = array.reshape(-1)
    if not np.isfinite(array).all():
        array = array[np.isfinite(array)]
    n = int(array.size)
    result: dict[str, Any] = {"method": "ar1_with_intercept", "n_signal_pairs": max(0, n - 1)}
    if n < 4:
        result["status"] = "insufficient_observations"
        return result
    previous = array[:-1]
    current = array[1:]
    centered_previous = previous - float(np.mean(previous))
    denominator = float(np.dot(centered_previous, centered_previous))
    if denominator <= 0:
        result["status"] = "degenerate_lagged_series"
        return result
    rho = float(np.dot(centered_previous, current - float(np.mean(current))) / denominator)
    intercept = float(np.mean(current) - rho * np.mean(previous))
    fitted = intercept + rho * previous
    residual_sum = float(np.sum((current - fitted) ** 2))
    total_sum = float(np.sum((current - float(np.mean(current))) ** 2))
    r_squared = 1.0 - residual_sum / total_sum if total_sum > 0 else 1.0
    result.update({
        "rho": rho,
        "intercept": intercept,
        "r_squared": float(r_squared),
    })
    if not math.isfinite(rho) or rho <= 0:
        result["status"] = "invalid_rho_nonpositive"
        return result
    if rho >= 1:
        result["status"] = "invalid_rho_nonstationary"
        return result
    half_life_signals = math.log(0.5) / math.log(rho)
    result.update({
        "status": "estimated",
        "half_life_signals": float(half_life_signals),
        "half_life_seconds": (
            float(half_life_signals * signal_interval_seconds)
            if signal_interval_seconds is not None and signal_interval_seconds > 0
            else None
        ),
        "signal_interval_seconds": signal_interval_seconds,
    })
    return result
