"""Model selection and diagnostics for forward-IC decay curves.

The signed forward-IC path is the source of truth.  A log-linear exponential
fit is only appropriate while the direction-aligned path stays positive.  A
sign reversal is therefore reported as a separate regime and, when the
number of horizons is small, explicitly requests a denser IC experiment.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

MIN_REVERSAL_FIT_HORIZONS = 12


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
    result.update({
        "more_horizons_recommended": True,
        "recommendation": (
            "检测到方向反转；不对当前稀疏 horizon 做分段直线拟合，"
            f"建议重新运行 IC 测试并至少提供 {minimum_reversal_fit_horizons} 个持有期 horizon，"
            "再拟合阻尼振荡指数曲线。"
        ),
    })
    return result
