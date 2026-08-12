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


_SHAPE_METRIC_NAMES = (
    "std_ic",
    "mad_ic",
    "iqr_ic",
    "q90_q10_ic",
    "median_abs_ic",
    "p90_abs_ic",
    "mean_abs_delta_ic",
    "mean_abs_second_delta_ic",
    "zero_crossing_rate",
    "path_max_drawdown",
    "path_drawdown_duration",
)

# Exact per-endpoint shape metrics are useful for short IC series, but their
# cost is O(number_of_windows * window_size) for quantiles and path metrics.
# High-frequency IC series can contain hundreds of thousands of dependent
# endpoints, so cap the deterministic endpoint sample used only for the shape
# distribution summary.  The full rolling window count remains reported by
# ``fast_rolling_metrics_many``; callers publish the sample metadata alongside
# the shape percentiles.
ROLLING_SHAPE_MAX_WINDOWS = 2_048


def _shape_window_indices(
    n_windows: int,
    *,
    max_windows: int = ROLLING_SHAPE_MAX_WINDOWS,
) -> np.ndarray:
    """Return deterministic, approximately uniform rolling-endpoint indices."""

    if n_windows <= 0:
        return np.empty(0, dtype=int)
    if n_windows <= max_windows:
        return np.arange(n_windows, dtype=int)
    # Include both endpoints so a short-lived regime at either boundary is not
    # silently omitted. ``unique`` handles any integer collisions defensively.
    return np.unique(
        np.linspace(0, n_windows - 1, max_windows, dtype=int),
    )


def _rolling_shape_metrics(
    values: np.ndarray,
    *,
    window: int,
    expected_sign: int | None,
    window_indices: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """Return per-window amplitude, roughness, and path diagnostics.

    The report uses one summary row per signal-count window, but high-frequency
    series can have hundreds of thousands of overlapping windows.  A strided
    view is therefore processed in bounded row chunks.  The input is already
    finite and compact; no timestamp or clock-duration inference is involved.
    """

    total_windows = max(0, values.size - window + 1)
    indices = (
        _shape_window_indices(total_windows)
        if window_indices is None
        else np.asarray(window_indices, dtype=int)
    )
    n_windows = int(indices.size)
    output = {
        name: np.full(n_windows, np.nan, dtype=float)
        for name in _SHAPE_METRIC_NAMES
    }
    if n_windows == 0:
        return output

    if window <= 1:
        output["std_ic"][:] = np.nan
        output["mad_ic"][:] = 0.0
        output["iqr_ic"][:] = 0.0
        output["q90_q10_ic"][:] = 0.0
        sampled_values = values[indices]
        output["median_abs_ic"][:] = np.abs(sampled_values)
        output["p90_abs_ic"][:] = np.abs(sampled_values)
        output["mean_abs_delta_ic"][:] = np.nan
        output["mean_abs_second_delta_ic"][:] = np.nan
        output["zero_crossing_rate"][:] = np.nan
        output["path_max_drawdown"][:] = 0.0
        output["path_drawdown_duration"][:] = 0.0
        return output

    view = np.lib.stride_tricks.sliding_window_view(values, window)
    # Bound the temporary window matrix to roughly 2M cells.  This keeps MIN1
    # jobs predictable while retaining exact per-window quantiles/MAD.
    chunk_rows = max(1, min(n_windows, 2_000_000 // max(window, 1)))
    sign = expected_sign if expected_sign in (-1, 1) else 1
    positions = np.arange(window, dtype=float)
    for start in range(0, n_windows, chunk_rows):
        stop = min(n_windows, start + chunk_rows)
        block = np.asarray(view[indices[start:stop]], dtype=float)
        quantiles = np.quantile(
            block, [0.10, 0.25, 0.50, 0.75, 0.90], axis=1,
        )
        median = quantiles[2]
        output["std_ic"][start:stop] = np.std(block, axis=1, ddof=1)
        output["mad_ic"][start:stop] = np.median(
            np.abs(block - median[:, None]), axis=1,
        )
        output["iqr_ic"][start:stop] = quantiles[3] - quantiles[1]
        output["q90_q10_ic"][start:stop] = quantiles[4] - quantiles[0]

        absolute = np.abs(block)
        absolute_quantiles = np.quantile(absolute, [0.50, 0.90], axis=1)
        output["median_abs_ic"][start:stop] = absolute_quantiles[0]
        output["p90_abs_ic"][start:stop] = absolute_quantiles[1]

        output["mean_abs_delta_ic"][start:stop] = np.mean(
            np.abs(np.diff(block, axis=1)), axis=1,
        )
        output["mean_abs_second_delta_ic"][start:stop] = (
            np.mean(np.abs(np.diff(block, n=2, axis=1)), axis=1)
            if window > 2 else np.nan
        )
        output["zero_crossing_rate"][start:stop] = np.count_nonzero(
            block[:, :-1] * block[:, 1:] < 0.0, axis=1,
        ) / float(window - 1)

        path = np.cumsum(sign * block, axis=1)
        baseline = np.zeros((path.shape[0], 1), dtype=float)
        peak = np.maximum.accumulate(
            np.concatenate((baseline, path), axis=1), axis=1,
        )[:, 1:]
        drawdown = peak - path
        output["path_max_drawdown"][start:stop] = np.max(drawdown, axis=1)
        underwater = drawdown > 0.0
        # At each endpoint, count the current consecutive underwater run;
        # taking its row maximum yields the longest recovery duration in
        # signal steps without a Python loop over every window.
        last_peak = np.maximum.accumulate(
            np.where(underwater, -1.0, positions[None, :]), axis=1,
        )
        run_lengths = np.where(underwater, positions[None, :] - last_peak, 0.0)
        output["path_drawdown_duration"][start:stop] = np.max(run_lengths, axis=1)
    return output


def _robust_scale_instability(
    scales: np.ndarray,
    *,
    fallback_scales: np.ndarray | None = None,
) -> float | None:
    """Return robust CV of per-window scales, or null when undefined."""

    scales = np.asarray(scales, dtype=float)
    finite = scales[np.isfinite(scales)]
    if fallback_scales is not None:
        fallback_scales = np.asarray(fallback_scales, dtype=float)
        if scales.shape == fallback_scales.shape:
            usable = np.where(
                np.isfinite(scales) & (scales > 0.0),
                scales,
                np.where(np.isfinite(fallback_scales), fallback_scales, np.nan),
            )
            finite = usable[np.isfinite(usable)]
        elif finite.size == 0:
            finite = fallback_scales[np.isfinite(fallback_scales)]
    if finite.size == 0:
        return None
    center = float(np.median(finite))
    if not math.isfinite(center) or center <= 0.0:
        return None
    mad = float(np.median(np.abs(finite - center)))
    return float(1.4826 * mad / center)


def _shape_summary(
    values: np.ndarray,
    *,
    window: int,
    expected_sign: int | None,
) -> dict[str, Any]:
    """Summarize per-window shape diagnostics across dependent windows."""

    total_windows = max(0, values.size - window + 1)
    indices = _shape_window_indices(total_windows)
    metrics = _rolling_shape_metrics(
        values,
        window=window,
        expected_sign=expected_sign,
        window_indices=indices,
    )
    summary: dict[str, Any] = {}
    for name, array in metrics.items():
        q10, q50, q90 = _quantiles(array)
        summary[f"rolling_{name}_p10"] = q10
        summary[f"rolling_{name}_p50"] = q50
        summary[f"rolling_{name}_p90"] = q90
    summary["rolling_scale_instability_rcv"] = _robust_scale_instability(
        metrics["mad_ic"], fallback_scales=metrics["iqr_ic"] / 1.349,
    )
    summary["rolling_shape_windows_evaluated"] = int(indices.size)
    summary["rolling_shape_sampling_stride"] = (
        float((total_windows - 1) / (indices.size - 1))
        if indices.size > 1 and indices.size < total_windows
        else 1.0
        if indices.size
        else None
    )
    summary["rolling_shape_sampling_status"] = (
        "uniform_endpoint_sampled"
        if indices.size < total_windows
        else "all_windows_exact"
        if indices.size
        else "not_estimable"
    )
    return summary


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
    shape_summary = _shape_summary(
        values, window=window, expected_sign=expected_sign,
    )
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
        **shape_summary,
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


def fast_rolling_metrics_many(
    series: pd.Series,
    *,
    expected_sign: int | None,
    support: TemporalSupport | None,
    resolutions: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Compute several signal-count windows in one HAC pass.

    The previous entry point recomputed ``values[j:] * values[:-j]`` for every
    window specification.  A factor with five windows therefore paid the same
    O(n × HAC-lag) product-prefix cost five times.  This routine shares the
    value prefixes and walks each HAC lag once, updating all requested windows.
    The returned payloads intentionally keep the old per-window schema.
    """

    values = (
        pd.Series(series)
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
        .to_numpy(dtype=float)
    )
    if not resolutions or values.size == 0:
        return {}

    prefix = np.concatenate(([0.0], np.cumsum(values, dtype=float)))
    prefix2 = np.concatenate(([0.0], np.cumsum(values * values, dtype=float)))
    states: list[dict[str, Any]] = []
    for resolution in resolutions:
        window = int(resolution["resolved_k_signals"])
        n_windows = max(0, values.size - window + 1)
        if n_windows <= 0:
            states.append({"resolution": resolution, "window": window, "n_windows": 0})
            continue
        ends = np.arange(window - 1, values.size, dtype=int)
        starts = ends - window + 1
        sums = prefix[ends + 1] - prefix[starts]
        means = sums / window
        sum_squares = prefix2[ends + 1] - prefix2[starts]
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
            oriented_prefix = np.concatenate((
                (0.0,), np.cumsum((oriented > 0).astype(float), dtype=float)
            ))
            direction_rate = (
                oriented_prefix[ends + 1] - oriented_prefix[starts]
            ) / window
            mean_sign_consistent = float(np.mean(expected_sign * means > 0))
            direction_consistent = float(np.mean(direction_rate >= 0.5))
            direction_failure_run_max = _longest_true_run(direction_rate < 0.5)
        else:
            direction_rate = np.full(n_windows, np.nan)
            mean_sign_consistent = None
            direction_consistent = None
            direction_failure_run_max = 0
        gamma0 = np.maximum(
            0.0, (sum_squares - (sums * sums) / window) / window,
        )
        states.append({
            "resolution": resolution,
            "window": window,
            "n_windows": n_windows,
            "ends": ends,
            "starts": starts,
            "means": means,
            "std": std,
            "icir": icir,
            "direction_rate": direction_rate,
            "mean_sign_consistent": mean_sign_consistent,
            "direction_consistent": direction_consistent,
            "direction_failure_run_max": direction_failure_run_max,
            "gamma0": gamma0,
            "long_run": gamma0.copy(),
        })

    hac_lag: int | None = None
    hac_status = "not_estimable"
    if support is not None:
        hac_resolution = resolve_hac_lag(support, max_lag=512)
        hac_lag = hac_resolution.lag
        hac_status = hac_resolution.status
    max_lag = max(
        (min(int(hac_lag), state["window"] - 1)
         for state in states if state.get("n_windows", 0) and hac_lag is not None),
        default=0,
    )
    if hac_lag is not None and max_lag > 0:
        for current_lag in range(1, max_lag + 1):
            product = values[current_lag:] * values[:-current_lag]
            product_prefix = np.concatenate(([0.0], np.cumsum(product, dtype=float)))
            for state in states:
                if not state.get("n_windows") or current_lag >= state["window"]:
                    continue
                window = state["window"]
                starts = state["starts"]
                ends = state["ends"]
                means = state["means"]
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
                used_lag = min(int(hac_lag), window - 1)
                weight = 1.0 - current_lag / (used_lag + 1.0)
                state["long_run"] += 2.0 * weight * gamma

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
    except (TypeError, ValueError, OverflowError):
        timestamp_ns = None

    result: dict[str, dict[str, Any]] = {}
    for state in states:
        resolution = state["resolution"]
        key = str(resolution.get("key"))
        n_windows = int(state.get("n_windows", 0))
        if n_windows <= 0:
            result[key] = {
                "rolling_windows_count": 0,
                "rolling_estimable": False,
                "rolling_detail_status": "summary_only",
                "rolling_detail_row_count": 0,
            }
            continue
        means = state["means"]
        icir = state["icir"]
        direction_rate = state["direction_rate"]
        if hac_lag is None:
            t_stat_hac = np.full(n_windows, np.nan)
            effective_n_ratio = np.full(n_windows, np.nan)
            ci_excludes_zero = np.zeros(n_windows, dtype=bool)
            hac_estimable_rate = 0.0
        else:
            long_run = np.maximum(0.0, state["long_run"])
            gamma0 = state["gamma0"]
            se_hac = np.sqrt(long_run / state["window"])
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
        capped_ratio = np.clip(effective_n_ratio, 1.0 / state["window"], 1.0)
        actual_endpoint_span = None
        actual_ratio = None
        if timestamp_ns is not None:
            starts = state["starts"]
            ends = state["ends"]
            actual_endpoint_span = (timestamp_ns[ends] - timestamp_ns[starts]) / 1e9
            expected_span = resolution.get("expected_endpoint_span_seconds")
            if expected_span not in (None, 0):
                actual_ratio = actual_endpoint_span / float(expected_span)
        mean_q10, mean_q50, mean_q90 = _quantiles(means)
        icir_q10, icir_q50, icir_q90 = _quantiles(icir)
        direction_q10, direction_q50, direction_q90 = _quantiles(direction_rate)
        t_q10, t_q50, t_q90 = _quantiles(t_stat_hac)
        ess_q10, ess_q50, ess_q90 = _quantiles(capped_ratio)
        shape_summary = _shape_summary(
            values,
            window=state["window"],
            expected_sign=expected_sign,
        )
        result[key] = {
            "rolling_windows_count": n_windows,
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
            "rolling_mean_sign_consistency_rate": state["mean_sign_consistent"],
            "rolling_direction_consistency_rate": state["direction_consistent"],
            "rolling_direction_failure_run_max": state["direction_failure_run_max"],
            "rolling_hac_estimable_rate": hac_estimable_rate,
            "rolling_hac_ci_excludes_zero_expected_direction_rate": (
                float(np.mean(ci_excludes_zero)) if hac_lag is not None else 0.0
            ),
            **shape_summary,
            "expected_endpoint_span_seconds": resolution.get("expected_endpoint_span_seconds"),
            "expected_coverage_span_seconds": resolution.get("expected_coverage_span_seconds"),
            "rolling_actual_endpoint_span_seconds_median": (
                float(np.median(actual_endpoint_span))
                if actual_endpoint_span is not None and actual_endpoint_span.size else None
            ),
            "rolling_actual_over_expected_span_median": (
                float(np.median(actual_ratio))
                if actual_ratio is not None and actual_ratio.size else None
            ),
        }
    return result


__all__ = ["fast_rolling_metrics", "fast_rolling_metrics_many"]
