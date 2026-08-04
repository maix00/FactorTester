"""Normalize IC Job results for chart and table artifact builders."""

from __future__ import annotations

from typing import Any


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


def ic_statistics_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for factor in result.get("factors") or ():
        if not isinstance(factor, dict):
            continue
        alias = str(factor.get("factor_alias") or factor.get("alias") or "")
        factor_ref = str(factor.get("factor_ref") or "")
        method = str(factor.get("ic_method") or "rank")
        half_life = factor.get("forward_ic_half_life") or {}
        exponential_half_life = factor.get("forward_ic_half_life_exponential") or {}
        for horizon, by_delay in (
            factor.get("ic_stats_by_forward_horizon") or {}
        ).items():
            if not isinstance(by_delay, dict):
                continue
            for delay, stats in by_delay.items():
                if not isinstance(stats, dict):
                    continue
                # Explicit names are the stable API.  The short aliases below
                # remain in the report row for older CSV consumers.
                mean_ic = stats.get("mean_ic", stats.get("mean"))
                std_ic = stats.get("std_ic", stats.get("std"))
                icir_signal = stats.get("icir_signal", stats.get("IR"))
                t_stat_iid = stats.get("t_stat_iid", stats.get("t_stat"))
                rows.append({
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
                    "forward_ic_half_life_exponential_status": exponential_half_life.get("status"),
                    "forward_ic_half_life_exponential_duration": exponential_half_life.get("duration"),
                    "forward_ic_half_life_exponential_seconds": exponential_half_life.get("half_life_seconds"),
                    "forward_ic_half_life_exponential_r_squared": exponential_half_life.get("r_squared"),
                    "forward_ic_half_life_exponential_n_horizons": exponential_half_life.get("n_horizons"),
                })
    return rows
