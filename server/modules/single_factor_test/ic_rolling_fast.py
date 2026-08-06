"""Vectorized rolling IC stability metrics for long signal sequences.

The report artifact is a one-row-per-window summary.  Expanding every
endpoint into a full ``summarize_ic_series`` call is both unnecessary for
that artifact and prohibitively expensive for minute data.  This module
computes the fields used by the summary with prefix sums and rolling arrays;
the detailed endpoint rows remain available for short sequences.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from tools.factors.temporal_support import TemporalSupport, resolve_hac_lag


def _quantile(values: np.ndarray) -> float | None:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None
    return float(np.quantile(finite, 0.5))


def _quantiles(values: np.ndarray) -> tuple[float | None, float | None, float | None]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None, None, None
    q10, q50, q90 = np.quantile(finite, [0.10, 0.50, 0.90])
    return float(q10), float(q50), float(q90)


def _rolling_sum(values: np.ndarray, window: int) -> np.ndarray:
    prefix = np.concatenate(([0.0], np.cumsum(values, dtype=float)))
    ends = np.arange(window - 1, values.size, dtype=int)
    starts = ends - window + 1
    return prefix[ends + 1] - prefix[starts]


def _longest_true_run(values: np.ndarray) -> int:
    if values.size == 0 or not bool(values.any()):
        return 0
    starts = np.flatnonzero(values & ~np.concatenate(([False], values[:-1])))
    ends = np.flatnonzero(values & ~np.concatenate((values[1:], [False])))
    return int(np.max(ends - starts + 1))


def _rolling_hac(
    values: np.ndarray,
    *,
    window: int,
    means: np.ndarray,
    lag: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return rolling Bartlett long-run variance and IID variance.

    For a window ending at ``e`` the lag-``j`` covariance uses exactly the
    same ``j .. K-1`` pairs as ``_newey_west``.  Prefix sums make each lag a
    vectorized O(T) pass instead of a Python loop over every endpoint.
    """

    starts = np.arange(window - 1, values.size, dtype=int) - window + 1
    ends = np.arange(window - 1, values.size, dtype=int)
    sum_x = _rolling_sum(values, window)
    sum_x2 = _rolling_sum(values * values, window)
    gamma0 = np.maximum(0.0, (sum_x2 - (sum_x * sum_x) / window) / window)
    used_lag = max(0, min(int(lag), window - 1))
    long_run = gamma0.copy()
    if used_lag == 0:
        return long_run, gamma0

    prefix = np.concatenate(([0.0], np.cumsum(values, dtype=float)))
    for current_lag in range(1, used_lag + 1):
        product = values[current_lag:] * values[:-current_lag]
        product_prefix = np.concatenate(([0.0], np.cumsum(product, dtype=float)))
        # Product index j corresponds to original index j + current_lag.
        sum_product = (
            product_prefix[ends - current_lag + 1]
            - product_prefix[starts]
        )
        sum_current = prefix[ends + 1] - prefix[starts + current_lag]
        sum_lagged = prefix[ends - current_lag + 1] - prefix[starts]
        pair_count = window - current_lag
        gamma = (
            sum_product
            - means * (sum_current + sum_lagged)
            + pair_count * means * means
        ) / window
        weight = 1.0 - current_lag / (used_lag + 1.0)
        long_run += 2.0 * weight * gamma
    return np.maximum(0.0, long_run), gamma0


def fast_rolling_metrics(
    series: pd.Series,
    *,
    expected_sign: int | None,
    support: TemporalSupport | None,
    resolution: dict[str, Any],
) -> dict[str, Any]:
    """Compute the rolling summary fields without materializing endpoint rows."""

    values = (
        pd.Series(series)
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
        .to_numpy(dtype=float)
    )
    window = int(resolution["resolved_k_signals"])
    n_windows = max(0, values.size - window + 1)
    if n_windows == 0:
        return {
            "rolling_windows_count": 0,
            "rolling_estimable": False,
            "rolling_detail_status": "summary_only",
            "rolling_detail_row_count": 0,
        }

    sums = _rolling_sum(values, window)
    means = sums / window
    sum_squares = _rolling_sum(values * values, window)
    variance = np.maximum(
        0.0,
        (sum_squares - (sums * sums) / window) / max(1, window - 1),
    )
    std = np.sqrt(variance)
    with np.errstate(divide="ignore", invalid="ignore"):
        icir = means / std
    icir[std <= 0] = np.nan

    if expected_sign in (-1, 1):
        oriented = expected_sign * values
        direction_rate = _rolling_sum((oriented > 0).astype(float), window) / window
        mean_sign_consistent = float(np.mean(expected_sign * means > 0))
        direction_consistent = float(np.mean(direction_rate >= 0.5))
        direction_failure_run_max = _longest_true_run(direction_rate < 0.5)
    else:
        direction_rate = np.full(n_windows, np.nan)
        mean_sign_consistent = None
        direction_consistent = None
        direction_failure_run_max = 0

    if support is None:
        hac_lag = None
        hac_status = "not_estimable"
    else:
        hac_resolution = resolve_hac_lag(support, max_lag=512)
        hac_lag = hac_resolution.lag
        hac_status = hac_resolution.status

    if hac_lag is None:
        t_stat_hac = np.full(n_windows, np.nan)
        effective_n_ratio = np.full(n_windows, np.nan)
        ci_excludes_zero = np.zeros(n_windows, dtype=bool)
        hac_estimable_rate = 0.0
    else:
        long_run, gamma0 = _rolling_hac(
            values, window=window, means=means, lag=hac_lag,
        )
        se_hac = np.sqrt(long_run / window)
        with np.errstate(divide="ignore", invalid="ignore"):
            t_stat_hac = means / se_hac
            effective_n_ratio = gamma0 / long_run
        t_stat_hac[se_hac <= 0] = np.nan
        effective_n_ratio[long_run <= 0] = np.nan
        se_hac = np.where(long_run > 0, se_hac, np.nan)
        lower = means - 1.96 * se_hac
        upper = means + 1.96 * se_hac
        sign = expected_sign if expected_sign in (-1, 1) else 1
        ci_excludes_zero = (sign * lower > 0) | (sign * upper < 0)
        hac_estimable_rate = 1.0 if hac_status == "estimable" else 0.0

    capped_ratio = np.clip(effective_n_ratio, 1.0 / window, 1.0)
    actual_endpoint_span = None
    actual_ratio = None
    try:
        index = series.replace([np.inf, -np.inf], np.nan).dropna().index
        if isinstance(index, pd.MultiIndex):
            name = next(
                (item for item in index.names if item and str(item).startswith("_SIGNAL")),
                None,
            )
            timestamps = pd.DatetimeIndex(index.get_level_values(name or -1))
        else:
            timestamps = pd.DatetimeIndex(index)
        timestamp_ns = timestamps.as_unit("ns").asi8
        starts = np.arange(window - 1, timestamp_ns.size, dtype=int) - window + 1
        ends = np.arange(window - 1, timestamp_ns.size, dtype=int)
        actual_endpoint_span = (timestamp_ns[ends] - timestamp_ns[starts]) / 1e9
        expected_span = resolution.get("expected_endpoint_span_seconds")
        if expected_span not in (None, 0):
            actual_ratio = actual_endpoint_span / float(expected_span)
    except (TypeError, ValueError, OverflowError):
        pass

    mean_q10, mean_q50, mean_q90 = _quantiles(means)
    icir_q10, icir_q50, icir_q90 = _quantiles(icir)
    direction_q10, direction_q50, direction_q90 = _quantiles(direction_rate)
    t_q10, t_q50, t_q90 = _quantiles(t_stat_hac)
    ess_q10, ess_q50, ess_q90 = _quantiles(capped_ratio)
    return {
        "rolling_windows_count": int(n_windows),
        "rolling_estimable": True,
        "rolling_detail_status": "summary_only",
        "rolling_detail_row_count": 0,
        "rolling_mean_ic_p10": mean_q10,
        "rolling_mean_ic_p50": mean_q50,
        "rolling_mean_ic_p90": mean_q90,
        "rolling_icir_p10": icir_q10,
        "rolling_icir_p50": icir_q50,
        "rolling_icir_p90": icir_q90,
        "rolling_direction_rate_p10": direction_q10,
        "rolling_direction_rate_p50": direction_q50,
        "rolling_direction_rate_p90": direction_q90,
        "rolling_t_stat_hac_p10": t_q10,
        "rolling_t_stat_hac_p50": t_q50,
        "rolling_t_stat_hac_p90": t_q90,
        "rolling_effective_n_ratio_p10": ess_q10,
        "rolling_effective_n_ratio_p50": ess_q50,
        "rolling_effective_n_ratio_p90": ess_q90,
        "rolling_mean_sign_consistency_rate": mean_sign_consistent,
        "rolling_direction_consistency_rate": direction_consistent,
        "rolling_direction_failure_run_max": direction_failure_run_max,
        "rolling_hac_estimable_rate": hac_estimable_rate,
        "rolling_hac_ci_excludes_zero_expected_direction_rate": (
            float(np.mean(ci_excludes_zero)) if hac_lag is not None else 0.0
        ),
        "expected_endpoint_span_seconds": resolution.get("expected_endpoint_span_seconds"),
        "expected_coverage_span_seconds": resolution.get("expected_coverage_span_seconds"),
        "rolling_actual_endpoint_span_seconds_median": (
            float(np.median(actual_endpoint_span))
            if actual_endpoint_span is not None and actual_endpoint_span.size
            else None
        ),
        "rolling_actual_over_expected_span_median": (
            float(np.median(actual_ratio))
            if actual_ratio is not None and actual_ratio.size
            else None
        ),
    }


__all__ = ["fast_rolling_metrics"]
