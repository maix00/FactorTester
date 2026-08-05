"""Model selection and diagnostics for forward-IC decay curves.

The signed forward-IC path is the source of truth.  A log-linear exponential
fit is only appropriate while the direction-aligned path stays positive.  A
sign reversal is therefore reported as a separate regime and, when the
number of horizons is small, explicitly requests a denser IC experiment.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np

MIN_REVERSAL_FIT_HORIZONS = 12


def _fit_damped_oscillatory(
    points: list[tuple[float, str, float]], direction: int,
) -> dict[str, float] | None:
    """Fit A exp(-lambda*t) cos(omega*t+phi)+c on a day-scaled grid."""
    try:
        from scipy.optimize import curve_fit
    except Exception:
        return None
    x = np.asarray([(seconds - points[0][0]) / 86400.0 for seconds, _label, _ in points], dtype=float)
    y = np.asarray([direction * mean for _seconds, _label, mean in points], dtype=float)
    if len(x) < MIN_REVERSAL_FIT_HORIZONS or np.ptp(x) <= 0:
        return None

    def model(time, amplitude, decay, frequency, phase, offset):
        return amplitude * np.exp(-decay * time) * np.cos(frequency * time + phase) + offset

    amplitude = max(float(np.max(np.abs(y))), 1e-3)
    span = max(float(np.ptp(x)), 1.0)
    initial = [amplitude, 0.05, math.pi / span, 0.0, 0.0]
    try:
        params, _ = curve_fit(
            model, x, y, p0=initial,
            bounds=([-2.0, 0.0, 0.0, -math.pi, -1.0], [2.0, 10.0, 20.0, math.pi, 1.0]),
            maxfev=20000,
        )
    except Exception:
        return None
    fitted = model(x, *params)
    residual = y - fitted
    ss_res = float(np.sum(residual ** 2))
    ss_tot = float(np.sum((y - float(np.mean(y))) ** 2))
    return {
        "amplitude": float(params[0]),
        "decay_per_day": float(params[1]),
        "frequency_per_day": float(params[2]),
        "phase": float(params[3]),
        "offset": float(params[4]),
        "r_squared": float(1.0 - ss_res / ss_tot) if ss_tot > 0 else 1.0,
        "rmse": float(math.sqrt(ss_res / len(x))),
    }


def select_forward_ic_decay_model(
    points: Iterable[tuple[float, str, float]],
    *,
    minimum_reversal_fit_horizons: int = MIN_REVERSAL_FIT_HORIZONS,
) -> dict[str, Any]:
    """Select a decay model and return sign/reversal diagnostics.

    With a reversal the function deliberately does not fit a curve from the
    sparse grid.  It requests a denser horizon grid for a five-parameter
    damped oscillatory exponential model instead.
    """

    clean = sorted(
        (float(seconds), str(label), float(mean))
        for seconds, label, mean in points
        if math.isfinite(float(seconds)) and float(seconds) > 0
        and math.isfinite(float(mean))
    )
    result: dict[str, Any] = {
        "selected_model": "not_estimable",
        "sign_reversal": False,
        "n_sign_changes": 0,
        "more_horizons_recommended": False,
        "recommended_min_horizons": int(minimum_reversal_fit_horizons),
    }
    if not clean:
        result["model_selection_status"] = "no_valid_horizons"
        return result
    baseline = clean[0][2]
    if abs(baseline) <= 1e-12:
        result.update({
            "model_selection_status": "zero_baseline_ic",
            "baseline_horizon": clean[0][1],
            "baseline_seconds": clean[0][0],
            "baseline_mean_ic": baseline,
        })
        return result
    direction = 1 if baseline > 0 else -1
    oriented = [(seconds, label, direction * mean) for seconds, label, mean in clean]
    changes: list[tuple[int, int]] = []
    for index, (previous, current) in enumerate(zip(oriented, oriented[1:]), start=1):
        if previous[2] * current[2] < 0:
            changes.append((index - 1, index))
    invalid = [index for index, item in enumerate(oriented) if item[2] <= 0]
    result.update({
        "baseline_horizon": clean[0][1],
        "baseline_seconds": clean[0][0],
        "baseline_mean_ic": baseline,
        "expected_direction": direction,
        "n_invalid_oriented_points": len(invalid),
        "first_invalid_horizon": oriented[invalid[0]][1] if invalid else None,
        "sign_reversal": bool(invalid),
        "n_sign_changes": len(changes),
    })
    if not invalid:
        result.update({
            "selected_model": "exponential",
            "model_selection_status": "exponential_eligible",
        })
        return result

    result["selected_model"] = "crossing_only"
    result["smooth_reversal_model"] = "damped_oscillatory_exponential"
    result["model_selection_status"] = "sign_reversal_detected"
    if len(clean) >= minimum_reversal_fit_horizons:
        smooth_fit = _fit_damped_oscillatory(clean, direction)
        if smooth_fit is not None:
            result.update({
                "selected_model": "damped_oscillatory_exponential",
                "model_selection_status": "smooth_reversal_fit_estimable",
                "more_horizons_recommended": False,
                "smooth_fit": smooth_fit,
                "recommendation": "已用阻尼振荡指数曲线拟合反转路径；仍需用留出 horizon 检验稳健性。",
            })
            return result
    result.update({
        "more_horizons_recommended": True,
        "recommendation": (
            "检测到方向反转；不对当前稀疏 horizon 做分段直线拟合，"
            f"建议重新运行 IC 测试并至少提供 {minimum_reversal_fit_horizons} 个持有期 horizon，"
            "再拟合阻尼振荡指数曲线。"
        ),
    })
    return result
