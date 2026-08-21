"""Normalize IC Job results for chart and table artifact builders.

The holding-period half-life output is deliberately separate from the regular
IC statistics table.  It is an on-demand, horizon-level calculation over the
already persisted horizon means; it never evaluates a factor or requests new
market data.
"""

from __future__ import annotations

import math
import re
from typing import Any

from tools.data.types import DataFreq
from tools.factors.tester_calc.single_factor_test.ic_diagnostics import (
    filter_ic_metric_mapping,
    ic_metric_selected,
    normalize_ic_metric_selection,
)
from tools.factors.tester_calc.single_factor_test.ic_half_life import (
    fit_forward_ic_half_life,
)


def _horizon_seconds(value: Any) -> float | None:
    """Resolve a FactorTester horizon name to seconds without alias guessing."""

    try:
        duration = DataFreq(str(value)).value
        seconds = float(duration.total_seconds())
    except (AttributeError, TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _stats_for_delay(by_delay: Any, delay: int) -> dict[str, Any] | None:
    if not isinstance(by_delay, dict):
        return None
    candidate = by_delay.get(str(delay))
    if candidate is None:
        candidate = by_delay.get(delay)
    return candidate if isinstance(candidate, dict) else None


def _half_life_direction_comparison(
    registered_direction: Any,
    observed_direction: Any,
) -> dict[str, Any]:
    """Compare a declared IC direction with the observed baseline direction.

    The half-life fitter deliberately infers its orientation from the observed
    baseline.  This report-level comparison keeps that inference separate from
    the factor's declared direction, so an estimated decay cannot silently be
    treated as confirmation of the directional hypothesis.
    """

    def _normalise(value: Any) -> int | None:
        try:
            candidate = int(value)
        except (TypeError, ValueError):
            return None
        return candidate if candidate in (-1, 1) else None

    registered = _normalise(registered_direction)
    observed = _normalise(observed_direction)
    if registered is None or observed is None:
        return {
            "registered_direction": registered,
            "observed_direction": observed,
            "direction_match": None,
            "direction_status": "not_comparable",
        }
    matches = registered == observed
    return {
        "registered_direction": registered,
        "observed_direction": observed,
        "direction_match": matches,
        "direction_status": "match" if matches else "mismatch",
    }


def ic_holding_half_life_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Return true forward-horizon half-life rows from saved IC summaries.

    ``H`` is the number of available forward horizons.  The fit is O(H) after
    the horizon means have been computed by the IC Job.  The returned points
    are retained for the optional plot and JSON data artifact.
    """

    selection = normalize_ic_metric_selection(result.get("ic_metric_selection"))
    if not ic_metric_selected(selection, "forward_ic_half_life"):
        return []
    rows: list[dict[str, Any]] = []
    for factor in result.get("factors") or ():
        if not isinstance(factor, dict):
            continue
        horizons = factor.get("ic_stats_by_forward_horizon") or {}
        if not isinstance(horizons, dict):
            continue
        aliases = factor.get("forward_ic_half_life_by_entry_delay") or {}
        delays: set[int] = set()
        for by_delay in horizons.values():
            if not isinstance(by_delay, dict):
                continue
            for raw_delay in by_delay:
                try:
                    delays.add(int(raw_delay))
                except (TypeError, ValueError):
                    continue
        for delay in sorted(delays):
            points: list[tuple[float, str, float]] = []
            for horizon, by_delay in horizons.items():
                stats = _stats_for_delay(by_delay, delay)
                if stats is None:
                    continue
                mean = stats.get("mean_ic", stats.get("mean"))
                seconds = _horizon_seconds(horizon)
                try:
                    mean_value = float(mean)
                except (TypeError, ValueError):
                    continue
                if seconds is None or not math.isfinite(mean_value):
                    continue
                points.append((seconds, str(horizon), mean_value))
            points.sort(key=lambda item: item[0])
            if not points:
                continue
            frequency_match = re.search(r"\$F:([^|]+)", str(factor.get("factor_alias") or factor.get("alias") or ""))
            factor_frequency_seconds = None
            if frequency_match:
                try:
                    factor_frequency_seconds = float(DataFreq(frequency_match.group(1)).value.total_seconds())
                except (AttributeError, TypeError, ValueError):
                    factor_frequency_seconds = None
            fitted = fit_forward_ic_half_life(
                points,
                entry_delay_bars=delay,
                baseline_seconds=factor_frequency_seconds,
            )
            expected_direction = fitted.get("expected_direction")
            display_direction = expected_direction
            if display_direction not in (-1, 1):
                display_direction = 1 if points[0][2] > 0 else -1 if points[0][2] < 0 else 1
            point_rows = [
                {
                    "horizon": horizon,
                    "horizon_seconds": seconds,
                    "mean_ic": float(mean),
                    "oriented_mean_ic": float(display_direction) * float(mean),
                }
                for seconds, horizon, mean in points
            ]
            crossing = aliases.get(str(delay)) if isinstance(aliases, dict) else None
            if not isinstance(crossing, dict):
                crossing = {}
            rows.append({
                "factor_alias": str(factor.get("factor_alias") or factor.get("alias") or ""),
                "factor_ref": str(factor.get("factor_ref") or ""),
                "ic_method": str(factor.get("ic_method") or "rank"),
                "entry_delay_bars": delay,
                "n_horizons": len(point_rows),
                "expected_direction": int(expected_direction) if expected_direction in (-1, 1) else None,
                "display_direction": int(display_direction),
                "baseline_horizon": fitted.get("baseline_horizon"),
                "baseline_seconds": fitted.get("baseline_seconds"),
                "baseline_mean_ic": fitted.get("baseline_mean_ic"),
                "n_invalid_oriented_points": fitted.get("n_invalid_oriented_points"),
                "last_horizon": fitted.get("last_horizon"),
                "curve_monotonic_nonincreasing": fitted.get("curve_monotonic_nonincreasing"),
                "exponential_status": fitted.get("status"),
                "exponential_half_life_seconds": fitted.get("half_life_seconds"),
                "exponential_r_squared": fitted.get("r_squared"),
                "exponential_log_decay_slope_per_second": fitted.get("log_decay_slope_per_second"),
                "exponential_log_decay_intercept": fitted.get("log_decay_intercept"),
                "exponential_log_fit_rmse": fitted.get("log_fit_rmse"),
                "selected_model": fitted.get("selected_model"),
                "smooth_reversal_model": fitted.get("smooth_reversal_model"),
                "smooth_fit": fitted.get("smooth_fit"),
                "model_selection_status": fitted.get("model_selection_status"),
                "sign_reversal": fitted.get("sign_reversal"),
                "n_sign_changes": fitted.get("n_sign_changes"),
                "more_horizons_recommended": fitted.get("more_horizons_recommended"),
                "recommended_min_horizons": fitted.get("recommended_min_horizons"),
                "recommendation": fitted.get("recommendation"),
                "crossing_status": crossing.get("status"),
                "crossing_half_life_seconds": crossing.get("seconds"),
                "crossing_duration": crossing.get("duration"),
                "crossing_baseline_horizon": crossing.get("baseline_horizon"),
                "crossing_baseline_seconds": crossing.get("baseline_seconds"),
                "crossing_baseline_mean_ic": crossing.get("baseline_mean_ic"),
                "crossing_half_amplitude_ic": crossing.get("half_amplitude_ic"),
                "crossing_first_horizon": crossing.get("first_crossing_before_or_at_horizon"),
                "crossing_last_horizon": crossing.get("last_horizon"),
                "crossing_n_nonpositive_oriented_points": crossing.get("n_nonpositive_oriented_points"),
                "crossing_first_nonpositive_horizon": crossing.get("first_nonpositive_horizon"),
                "crossing_curve_monotonic_nonincreasing": crossing.get("curve_monotonic_nonincreasing"),
                "points": point_rows,
            })
    return rows


def ic_series(result: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for factor in result.get("factors") or ():
        if not isinstance(factor, dict):
            continue
        alias = str(factor.get("factor_alias") or factor.get("alias") or "")
        factor_ref = str(factor.get("factor_ref") or "")
        method = str(factor.get("ic_method") or "rank")
        series_items = factor.get("ic_series_by_forward_horizon") or ()
        if not series_items and isinstance(factor.get("ic_series"), dict):
            series_items = [{
                **factor["ic_series"],
                "horizon": factor.get("primary_forward_return_horizon") or "",
                "entry_delay_bars": 0,
            }]
        for item in series_items:
            if not isinstance(item, dict):
                continue
            dates = list(item.get("dates") or ())
            values = list(item.get("values") or ())
            if not dates or len(dates) != len(values):
                continue
            horizon = str(item.get("horizon") or "")
            delay = int(item.get("entry_delay_bars") or 0)
            output.append({
                "label": f"{alias} · {method} · {horizon} · delay={delay}",
                "factor_alias": alias,
                "factor_ref": factor_ref,
                "ic_method": method,
                "forward_return_horizon": horizon,
                "entry_delay_bars": delay,
                "timestamps": dates,
                "values": values,
            })
    return output


def ic_resample_stability_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the IC response's deterministic resampling diagnostics."""

    rows: list[dict[str, Any]] = []
    for factor in result.get("factors") or ():
        if not isinstance(factor, dict):
            continue
        alias = str(factor.get("factor_alias") or factor.get("alias") or "")
        ref = str(factor.get("factor_ref") or "")
        method = str(factor.get("ic_method") or "rank")
        values = factor.get("ic_resample_stability")
        if not isinstance(values, list):
            values = (factor.get("ic_statistics") or {}).get("resample_stability")
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            rows.append({
                "factor_alias": alias,
                "factor_ref": ref,
                "ic_method": method,
                **item,
            })
    return rows


def ic_autocorrelation_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the cached IC-series autocorrelation for the table artifact."""

    rows: list[dict[str, Any]] = []
    for factor in result.get("factors") or ():
        if not isinstance(factor, dict):
            continue
        alias = str(factor.get("factor_alias") or factor.get("alias") or "")
        ref = str(factor.get("factor_ref") or "")
        method = str(factor.get("ic_method") or "rank")
        values = factor.get("autocorr")
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            rows.append({
                "factor_alias": alias,
                "factor_ref": ref,
                "ic_method": method,
                "lag": item.get("lag"),
                "autocorrelation": item.get("ac", item.get("value")),
            })
    return rows


def ic_statistics_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    selection = normalize_ic_metric_selection(result.get("ic_metric_selection"))
    identity_fields = {
        "factor_alias", "factor_ref", "ic_method", "forward_return_horizon",
        "entry_delay_bars",
    }
    for factor in result.get("factors") or ():
        if not isinstance(factor, dict):
            continue
        alias = str(factor.get("factor_alias") or factor.get("alias") or "")
        factor_ref = str(factor.get("factor_ref") or "")
        method = str(factor.get("ic_method") or "rank")
        half_life_by_delay = factor.get("forward_ic_half_life_by_entry_delay") or {}
        exponential_half_life_by_delay = factor.get(
            "forward_ic_half_life_exponential_by_entry_delay"
        ) or {}
        default_half_life = factor.get("forward_ic_half_life") or {}
        default_exponential_half_life = factor.get(
            "forward_ic_half_life_exponential"
        ) or {}
        for horizon, by_delay in (
            factor.get("ic_stats_by_forward_horizon") or {}
        ).items():
            if not isinstance(by_delay, dict):
                continue
            for delay, stats in by_delay.items():
                if not isinstance(stats, dict):
                    continue
                try:
                    delay_i = int(delay)
                except (TypeError, ValueError):
                    delay_i = 0
                half_life = _stats_for_delay(half_life_by_delay, delay_i) or default_half_life
                exponential_half_life = (
                    _stats_for_delay(exponential_half_life_by_delay, delay_i)
                    or default_exponential_half_life
                )
                direction_comparison = _half_life_direction_comparison(
                    stats.get("expected_sign"),
                    half_life.get("expected_direction")
                    if isinstance(half_life, dict)
                    else exponential_half_life.get("expected_direction"),
                )
                if direction_comparison["observed_direction"] is None:
                    direction_comparison = _half_life_direction_comparison(
                        stats.get("expected_sign"),
                        exponential_half_life.get("expected_direction")
                        if isinstance(exponential_half_life, dict) else None,
                    )
                # Explicit names are the stable API.  The short aliases below
                # remain in the report row for older CSV consumers.
                mean_ic = stats.get("mean_ic", stats.get("mean"))
                std_ic = stats.get("std_ic", stats.get("std"))
                icir_signal = stats.get("icir_signal", stats.get("IR"))
                t_stat_iid = stats.get("t_stat_iid", stats.get("t_stat"))
                row = {
                    "factor_alias": alias,
                    "factor_ref": factor_ref,
                    "ic_method": method,
                    "forward_return_horizon": str(horizon),
                    "entry_delay_bars": int(delay),
                    "diagnostics_schema": stats.get("diagnostics_schema"),
                    "n_signal_observations": stats.get("n_signal_observations", stats.get("n")),
                    "mean_ic": mean_ic,
                    "median_ic": stats.get("median_ic"),
                    "std_ic": std_ic,
                    "std_ic_ddof": stats.get("std_ic_ddof", 1),
                    "se_iid": stats.get("se_iid"),
                    "ci95_iid_lower": stats.get("ci95_iid_lower"),
                    "ci95_iid_upper": stats.get("ci95_iid_upper"),
                    "mad_ic": stats.get("mad_ic"),
                    "icir_signal": icir_signal,
                    "t_stat_iid": t_stat_iid,
                    "t_stat_hac": stats.get("t_stat_hac"),
                    "se_hac": stats.get("se_hac"),
                    "ci95_hac_lower": stats.get("ci95_hac_lower"),
                    "ci95_hac_upper": stats.get("ci95_hac_upper"),
                    "hac_lag": stats.get("hac_lag"),
                    "hac_lag_source": stats.get("hac_lag_source"),
                    "hac_lag_formula": stats.get("hac_lag_formula"),
                    "hac_kernel": stats.get("hac_kernel"),
                    "hac_status": stats.get("hac_status"),
                    "hac_reason": stats.get("hac_reason"),
                    "hac_overlap_support_seconds": stats.get("hac_overlap_support_seconds"),
                    "hac_overlap_support_components_seconds": stats.get("hac_overlap_support_components_seconds"),
                    "effective_n_raw": stats.get("effective_n_raw"),
                    "effective_n_capped": stats.get("effective_n_capped"),
                    "effective_n_ratio": stats.get("effective_n_ratio"),
                    "effective_n_capped_ratio": stats.get("effective_n_capped_ratio"),
                    "ess_exceeds_n": stats.get("ess_exceeds_n"),
                    "hac_lrv_to_iid_variance_ratio": stats.get("hac_lrv_to_iid_variance_ratio"),
                    "direction_rate": stats.get("direction_rate"),
                    "direction_rate_status": stats.get("direction_rate_status"),
                    "expected_sign": stats.get("expected_sign"),
                    "expected_sign_source": stats.get("expected_sign_source"),
                    "forward_ic_half_life_registered_direction": direction_comparison[
                        "registered_direction"
                    ],
                    "forward_ic_half_life_observed_direction": direction_comparison[
                        "observed_direction"
                    ],
                    "forward_ic_half_life_direction_match": direction_comparison[
                        "direction_match"
                    ],
                    "forward_ic_half_life_direction_status": direction_comparison[
                        "direction_status"
                    ],
                    "positive_ic_rate": stats.get("positive_ic_rate"),
                    "negative_ic_rate": stats.get("negative_ic_rate"),
                    "zero_ic_rate": stats.get("zero_ic_rate"),
                    "minimum_ic": stats.get("minimum_ic", stats.get("min")),
                    "maximum_ic": stats.get("maximum_ic", stats.get("max")),
                    "p10_ic": stats.get("p10_ic"),
                    "p25_ic": stats.get("p25_ic"),
                    "p50_ic": stats.get("p50_ic"),
                    "p75_ic": stats.get("p75_ic"),
                    "p90_ic": stats.get("p90_ic"),
                    "skew_ic": stats.get("skew_ic"),
                    "excess_kurtosis_ic": stats.get("excess_kurtosis_ic"),
                    "ic_series_acf1": stats.get("ic_series_acf1", stats.get("ac1")),
                    "acf_estimator": stats.get("acf_estimator"),
                    "ic_series_acf_half_life_status": stats.get("ic_series_acf_half_life_status"),
                    "ic_series_acf_half_life_signals": stats.get(
                        "ic_series_acf_half_life_signals",
                        stats.get("ic_series_acf_half_life"),
                    ),
                    "ic_series_ar1_rho": stats.get("ic_series_ar1_rho"),
                    "ic_series_ar1_r_squared": stats.get("ic_series_ar1_r_squared"),
                    "ic_series_ar1_half_life_status": stats.get("ic_series_ar1_half_life_status"),
                    "ic_series_ar1_half_life_signals": stats.get("ic_series_ar1_half_life_signals"),
                    "ic_series_ar1_half_life_seconds": stats.get("ic_series_ar1_half_life_seconds"),
                    "ic_series_ar1_n_signal_pairs": stats.get("ic_series_ar1_n_signal_pairs"),
                    "ic_series_ar1_method": stats.get("ic_series_ar1_method"),
                    "ess_definition": stats.get("ess_definition"),
                    "t_stat_hac_reference": stats.get("t_stat_hac_reference"),
                    # Deprecated aliases kept for existing report readers.
                    "std": std_ic,
                    "ir": icir_signal,
                    "t_stat": t_stat_iid,
                    "minimum": stats.get("minimum_ic", stats.get("min")),
                    "maximum": stats.get("maximum_ic", stats.get("max")),
                    "ac1": stats.get("ic_series_acf1", stats.get("ac1")),
                    "ic_series_acf_half_life": stats.get(
                        "ic_series_acf_half_life_signals",
                        stats.get("ic_series_acf_half_life"),
                    ),
                    "forward_ic_half_life_status": half_life.get("status"),
                    "forward_ic_half_life_duration": half_life.get("duration"),
                    "forward_ic_half_life_crossing_seconds": half_life.get("seconds"),
                    "forward_ic_half_life_crossing_duration": half_life.get("duration"),
                    "forward_ic_half_life_n_horizons": half_life.get("n_horizons"),
                    "forward_ic_half_life_crossing_baseline_horizon": half_life.get("baseline_horizon"),
                    "forward_ic_half_life_crossing_baseline_seconds": half_life.get("baseline_seconds"),
                    "forward_ic_half_life_crossing_baseline_mean_ic": half_life.get("baseline_mean_ic"),
                    "forward_ic_half_life_crossing_expected_direction": half_life.get("expected_direction"),
                    "forward_ic_half_life_baseline_horizon": half_life.get("baseline_horizon"),
                    "forward_ic_half_life_baseline_seconds": half_life.get("baseline_seconds"),
                    "forward_ic_half_life_baseline_mean_ic": half_life.get("baseline_mean_ic"),
                    "forward_ic_half_life_expected_direction": half_life.get("expected_direction"),
                    "forward_ic_half_life_curve_monotonic_nonincreasing": half_life.get("curve_monotonic_nonincreasing"),
                    "forward_ic_half_life_half_amplitude_ic": half_life.get("half_amplitude_ic"),
                    "forward_ic_half_life_first_crossing_horizon": half_life.get("first_crossing_before_or_at_horizon"),
                    "forward_ic_half_life_last_horizon": half_life.get("last_horizon"),
                    "forward_ic_half_life_crossing_n_nonpositive_oriented_points": half_life.get("n_nonpositive_oriented_points"),
                    "forward_ic_half_life_crossing_first_nonpositive_horizon": half_life.get("first_nonpositive_horizon"),
                    "forward_ic_half_life_crossing_curve_monotonic_nonincreasing": half_life.get("curve_monotonic_nonincreasing"),
                    "forward_ic_half_life_exponential_status": exponential_half_life.get("status"),
                    "forward_ic_half_life_exponential_duration": exponential_half_life.get("duration"),
                    "forward_ic_half_life_exponential_seconds": exponential_half_life.get("half_life_seconds"),
                    "forward_ic_half_life_exponential_r_squared": exponential_half_life.get("r_squared"),
                    "forward_ic_half_life_exponential_n_horizons": exponential_half_life.get("n_horizons"),
                    "forward_ic_half_life_exponential_baseline_horizon": exponential_half_life.get("baseline_horizon"),
                    "forward_ic_half_life_exponential_baseline_seconds": exponential_half_life.get("baseline_seconds"),
                    "forward_ic_half_life_exponential_baseline_mean_ic": exponential_half_life.get("baseline_mean_ic"),
                    "forward_ic_half_life_exponential_expected_direction": exponential_half_life.get("expected_direction"),
                    "forward_ic_half_life_exponential_n_invalid_oriented_points": exponential_half_life.get("n_invalid_oriented_points"),
                    "forward_ic_half_life_exponential_curve_monotonic_nonincreasing": exponential_half_life.get("curve_monotonic_nonincreasing"),
                    "forward_ic_half_life_exponential_log_decay_slope_per_second": exponential_half_life.get("log_decay_slope_per_second"),
                    "forward_ic_half_life_exponential_log_decay_intercept": exponential_half_life.get("log_decay_intercept"),
                    "forward_ic_half_life_exponential_log_fit_rmse": exponential_half_life.get("log_fit_rmse"),
                    "forward_ic_half_life_exponential_selected_model": exponential_half_life.get("selected_model"),
                    "forward_ic_half_life_exponential_smooth_reversal_model": exponential_half_life.get("smooth_reversal_model"),
                    "forward_ic_half_life_exponential_model_selection_status": exponential_half_life.get("model_selection_status"),
                    "forward_ic_half_life_exponential_sign_reversal": exponential_half_life.get("sign_reversal"),
                    "forward_ic_half_life_exponential_n_sign_changes": exponential_half_life.get("n_sign_changes"),
                    "forward_ic_half_life_exponential_more_horizons_recommended": exponential_half_life.get("more_horizons_recommended"),
                    "forward_ic_half_life_exponential_recommended_min_horizons": exponential_half_life.get("recommended_min_horizons"),
                    "forward_ic_half_life_exponential_recommendation": exponential_half_life.get("recommendation"),
                }
                rows.append(filter_ic_metric_mapping(
                    row, selection, preserve=identity_fields,
                ))
    return rows


def quantile_portfolio_statistics_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the IC response's vectorized grouped-return category.

    This is deliberately a separate table: correlation rows and portfolio
    rows have different units and must not be averaged into one statistic.
    """
    rows: list[dict[str, Any]] = []
    for factor in result.get("factors") or ():
        if not isinstance(factor, dict):
            continue
        statistics = factor.get("ic_statistics") or {}
        portfolio = statistics.get("quantile_portfolio_statistics") or {}
        if portfolio.get("status") != "computed":
            continue
        identity = {
            "factor_alias": str(factor.get("factor_alias") or factor.get("alias") or ""),
            "factor_ref": str(factor.get("factor_ref") or ""),
            "ic_method": str(factor.get("ic_method") or "rank"),
            "forward_return_horizon": str(factor.get("primary_forward_return_horizon") or ""),
            "entry_delay_bars": int(factor.get("primary_entry_delay_bars") or 0),
            "group_count": portfolio.get("group_count"),
            "product_count": portfolio.get("product_count"),
            "initial_capital": portfolio.get("initial_capital"),
            "capital_normalization": portfolio.get("capital_normalization"),
            "target_margin_utilization": portfolio.get("target_margin_utilization"),
            "rate_semantics": portfolio.get("rate_semantics"),
            "source_scope": portfolio.get("source_scope"),
            "fee_semantics": portfolio.get("fee_semantics"),
            "margin_semantics": portfolio.get("margin_semantics"),
        }
        portfolio_variants = [(
            str(factor.get("primary_forward_return_horizon") or ""),
            int(factor.get("primary_entry_delay_bars") or 0),
            portfolio,
        )]
        by_horizon = portfolio.get("by_forward_horizon") or {}
        for horizon, by_lag in by_horizon.items():
            if not isinstance(by_lag, dict):
                continue
            for lag, value in by_lag.items():
                if isinstance(value, dict):
                    try:
                        lag_i = int(lag)
                    except (TypeError, ValueError):
                        lag_i = 0
                    portfolio_variants.append((str(horizon), lag_i, value))
        seen_variants: set[tuple[str, int]] = set()
        for horizon, delay, variant in portfolio_variants:
            if (horizon, delay) in seen_variants:
                continue
            seen_variants.add((horizon, delay))
            variant_identity = {
                **identity,
                "forward_return_horizon": horizon or identity["forward_return_horizon"],
                "entry_delay_bars": delay,
                "source_scope": variant.get("source_scope", identity["source_scope"]),
                "fee_semantics": variant.get("fee_semantics", identity["fee_semantics"]),
                "margin_semantics": variant.get("margin_semantics", identity["margin_semantics"]),
            }
            for mode, payload in (variant.get("modes") or {}).items():
                if not isinstance(payload, dict):
                    continue
                monotonicity = payload.get("monotonicity") or {}
                top_bottom = monotonicity.get("top_bottom") or {}
                for portfolio_kind, item in [
                    ("group", group) for group in (payload.get("groups") or ())
                ] + [("long_short", payload.get("long_short") or {})]:
                    if not isinstance(item, dict):
                        continue
                    metrics = item.get("metrics") or {}
                    rows.append({
                        **variant_identity,
                        "portfolio_mode": str(mode),
                        "portfolio_kind": portfolio_kind,
                        "group_index": item.get("group_index"),
                        "total_return": metrics.get("Total Return"),
                        "annual_return": metrics.get("Annual Return"),
                        "volatility": metrics.get("Volatility"),
                        "sharpe_ratio": metrics.get("Sharpe Ratio"),
                        "max_drawdown": metrics.get("Max Drawdown"),
                        "calmar_ratio": metrics.get("Calmar Ratio"),
                        "win_rate": metrics.get("Win Rate"),
                        "mean_return": metrics.get("Mean Return"),
                        "avg_turnover": metrics.get("Avg Turnover"),
                        "comparable_period_count": monotonicity.get("comparable_period_count"),
                        "monotonic_period_ratio": monotonicity.get("monotonic_period_ratio"),
                        "descending_period_ratio": monotonicity.get("descending_period_ratio"),
                        "mean_rank_correlation": monotonicity.get("mean_rank_correlation"),
                        "top_bottom_mean_spread": top_bottom.get("mean_spread"),
                        "top_bottom_positive_ratio": top_bottom.get("positive_ratio"),
                        "turnover_proxy": payload.get("turnover_proxy"),
                        "long_short_turnover_proxy": payload.get("long_short_turnover_proxy"),
                        "turnover_semantics": (
                            variant.get("turnover_semantics")
                            or portfolio.get("turnover_semantics")
                            or "target-weight turnover proxy; not actual fills"
                        ),
                    })
    return rows
