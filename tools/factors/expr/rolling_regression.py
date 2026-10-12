"""Shared rolling time-trend regression metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd

ROLLING_LINEAR_METRICS = frozenset(
    {
        "rolling_linreg_slope",
        "rolling_linreg_r2",
        "rolling_linreg_tstat",
        "rolling_linreg_resid_std",
    }
)


def linear_metric(values: np.ndarray, metric: str, minimum: int) -> float:
    """Calculate one OLS time-trend metric on a single rolling window."""
    valid = np.isfinite(values)
    if valid.sum() < minimum:
        return np.nan
    y = values[valid]
    centered_y = y - y.mean()
    x = np.flatnonzero(valid).astype(float)
    centered_x = x - x.mean()
    sxx = float(centered_x @ centered_x)
    if sxx <= 0:
        return np.nan
    design = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(design, centered_y, rcond=None)
    residuals = centered_y - design @ beta
    sse = float(residuals @ residuals)
    sst = float(centered_y @ centered_y)

    if metric == "rolling_linreg_slope":
        return float(beta[1])
    if metric == "rolling_linreg_r2":
        return np.nan if sst <= 0 else 1.0 - sse / sst
    residual_variance = sse / (len(y) - 2)
    if metric == "rolling_linreg_resid_std":
        return float(np.sqrt(residual_variance))
    if metric == "rolling_linreg_tstat":
        standard_error = np.sqrt(residual_variance / sxx)
        if not np.isfinite(standard_error) or standard_error <= 0:
            return np.nan
        return float(beta[1] / standard_error)
    raise ValueError(f"Unknown rolling linear metric: {metric}")


def rolling_linear_metric(data: pd.DataFrame, window: int, metric: str) -> pd.DataFrame:
    """Vectorized rolling OLS using sufficient statistics."""
    if metric not in ROLLING_LINEAR_METRICS:
        raise ValueError(f"Unknown rolling linear metric: {metric}")
    minimum = max(3, window // 2)
    values = data.to_numpy(dtype=float, copy=False)
    if values.shape[0] == 0 or values.shape[1] == 0:
        return pd.DataFrame(index=data.index, columns=data.columns, dtype=float)
    finite_values = np.isfinite(values)
    first_valid_rows = finite_values.argmax(axis=0)
    column_indexes = np.arange(values.shape[1])
    anchors = values[first_valid_rows, column_indexes]
    anchors = np.where(finite_values.any(axis=0), anchors, 0.0)
    centered_values = np.where(finite_values, values - anchors, 0.0)
    valid = pd.DataFrame(finite_values, index=data.index, columns=data.columns)
    y = pd.DataFrame(centered_values, index=data.index, columns=data.columns)
    positions = np.broadcast_to(
        np.arange(len(data), dtype=float)[:, None],
        data.shape,
    )
    x = pd.DataFrame(
        np.where(valid, positions, 0.0),
        index=data.index,
        columns=data.columns,
    )

    def rolling_sum(values: pd.DataFrame) -> pd.DataFrame:
        return values.rolling(window, min_periods=1).sum()

    count = rolling_sum(valid.astype(float))
    sum_x = rolling_sum(x)
    sum_y = rolling_sum(y)
    sum_x2 = rolling_sum(x * x)
    sum_y2 = rolling_sum(y * y)
    sum_xy = rolling_sum(x * y)

    centered_xx = sum_x2 - sum_x * sum_x / count
    centered_yy = sum_y2 - sum_y * sum_y / count
    centered_xy = sum_xy - sum_x * sum_y / count
    slope = centered_xy / centered_xx
    intercept = (sum_y - slope * sum_x) / count
    sse = (sum_y2 - intercept * sum_y - slope * sum_xy).clip(lower=0.0)
    eligible = (count >= minimum) & (centered_xx > 0)

    if metric == "rolling_linreg_slope":
        result = slope
    elif metric == "rolling_linreg_r2":
        result = 1.0 - sse / centered_yy.where(centered_yy > 0)
    else:
        residual_variance = sse / (count - 2)
        if metric == "rolling_linreg_resid_std":
            result = np.sqrt(residual_variance)
        else:
            standard_error = np.sqrt(residual_variance / centered_xx)
            result = slope / standard_error.where(standard_error > 0)
    return result.where(eligible)
