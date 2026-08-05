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


MIN_REVERSAL_FIT_HORIZONS = 8


def _fit_line(points: list[tuple[float, float]]) -> dict[str, float] | None:
    if len(points) < 2:
        return None
    x = np.asarray([item[0] for item in points], dtype=float)
    y = np.asarray([item[1] for item in points], dtype=float)
    if np.ptp(x) <= 0:
        return None
    slope, intercept = np.polyfit(x, y, 1)
    fitted = intercept + slope * x
    ss_res = float(np.sum((y - fitted) ** 2))
    ss_tot = float(np.sum((y - float(np.mean(y))) ** 2))
    return {
        "slope_per_second": float(slope),
        "intercept": float(intercept),
        "r_squared": float(1.0 - ss_res / ss_tot) if ss_tot > 0 else 1.0,
        "rmse": float(math.sqrt(ss_res / len(points))),
    }


def select_forward_ic_decay_model(
    points: Iterable[tuple[float, str, float]],
    *,
    minimum_reversal_fit_horizons: int = MIN_REVERSAL_FIT_HORIZONS,
) -> dict[str, Any]:
    """Select a decay model and return sign/reversal diagnostics.

    With a reversal and fewer than ``minimum_reversal_fit_horizons`` points,
    the function deliberately does not fit a curve: it requests a denser
    horizon grid.  With enough points it selects a two-regime piecewise-linear
    model around the first sign crossing.
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

    result["selected_model"] = "piecewise_linear_sign_reversal" if len(clean) >= minimum_reversal_fit_horizons else "crossing_only"
    result["model_selection_status"] = "sign_reversal_detected"
    if len(clean) < minimum_reversal_fit_horizons:
        result.update({
            "more_horizons_recommended": True,
            "recommendation": (
                "检测到方向反转；当前 horizon 点不足以拟合反转曲线，"
                f"建议重新运行 IC 测试并至少提供 {minimum_reversal_fit_horizons} 个持有期 horizon。"
            ),
        })
        return result

    split = invalid[0]
    pre = [(seconds, value) for seconds, _label, value in oriented[: split + 1]]
    post = [(seconds, value) for seconds, _label, value in oriented[split:]]
    result["piecewise_pre_fit"] = _fit_line(pre)
    result["piecewise_post_fit"] = _fit_line(post)
    result["recommendation"] = "使用分段线性反转模型；同时保留过零点和半幅交叉诊断。"
    return result
