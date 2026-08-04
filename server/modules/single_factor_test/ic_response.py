"""Build JSON/SSE response payloads from computed IC state."""

from __future__ import annotations

from typing import Any, Dict, List, cast

import numpy as np
import pandas as pd

from tools.data.types import DataFreq
from tools.factors.tester_calc.single_factor_test.ic_diagnostics import (
    expected_sign_for_factor,
    metric_semantics_catalog,
    summarize_ic_series,
)
from tools.factors.tester_calc.single_factor_test.ic_half_life import (
    fit_forward_ic_half_life,
)
from server.modules.single_factor_test.ic_diagnostics import (
    json_safe_diagnostic_value,
    period_diagnostics,
    serialise_stats_series,
    temporal_support_from_dict,
)


def _extract_signal_index(idx: pd.Index) -> pd.DatetimeIndex:
    if isinstance(idx, pd.MultiIndex):
        signal_name = next(
            (name for name in idx.names if name and str(name).startswith('_SIGNAL')),
            None,
        )
        level = idx.names.index(signal_name) if signal_name is not None else -1
        return pd.DatetimeIndex(idx.get_level_values(level), name=idx.names[level])
    return pd.DatetimeIndex(idx)


def _safe_round(value: Any, ndigits: int = 6) -> Any:
    if value is None:
        return None
    try:
        number = float(value)
    except Exception:
        return None
    if np.isnan(number) or np.isinf(number):
        return None
    return round(number, ndigits)


def _forward_ic_half_life(
    stats_by_horizon: Dict[str, Dict[int, pd.Series]], entry_delay_bars: int,
) -> dict:
    """Estimate forward-horizon half-amplitude crossing, not IC ACF half-life."""
    points: list[tuple[pd.Timedelta, str, float]] = []
    for horizon, by_delay in stats_by_horizon.items():
        stats = by_delay.get(entry_delay_bars)
        mean = (
            stats.get('mean_ic', stats.get('mean'))
            if isinstance(stats, pd.Series) else None
        )
        try:
            mean_value = float(mean)
            duration = DataFreq(horizon).value
        except Exception:
            continue
        if duration > pd.Timedelta(0) and np.isfinite(mean_value):
            points.append((duration, horizon, mean_value))
    points.sort(key=lambda item: item[0])
    if len(points) < 2:
        result = {
            'status': 'insufficient_horizons',
            'entry_delay_bars': entry_delay_bars,
            'n_horizons': len(points),
        }
        if points:
            duration, horizon, mean = points[0]
            result.update({
                'baseline_horizon': horizon,
                'baseline_seconds': _safe_round(duration.total_seconds()),
                'baseline_mean_ic': _safe_round(mean),
                'expected_direction': 1 if mean > 0 else -1 if mean < 0 else None,
                'last_horizon': horizon,
            })
        return result
    _base_duration, base_horizon, base_ic = points[0]
    if abs(base_ic) <= 1e-12:
        return {
            'status': 'zero_baseline_ic', 'entry_delay_bars': entry_delay_bars,
            'n_horizons': len(points),
            'baseline_horizon': base_horizon,
            'baseline_seconds': _safe_round(_base_duration.total_seconds()),
            'baseline_mean_ic': _safe_round(base_ic),
            'expected_direction': None,
            'last_horizon': points[-1][1],
        }
    direction = 1.0 if base_ic > 0 else -1.0
    threshold = abs(base_ic) / 2.0
    oriented = [(duration, horizon, mean * direction) for duration, horizon, mean in points]
    monotonic = all(
        later[2] <= earlier[2] + 1e-12
        for earlier, later in zip(oriented, oriented[1:])
    )
    nonpositive = [item for item in oriented if item[2] <= 1e-12]
    for previous, current in zip(oriented, oriented[1:]):
        if current[2] > threshold:
            continue
        left_duration, _left_horizon, left_ic = previous
        right_duration, right_horizon, right_ic = current
        fraction = 0.0 if right_ic == left_ic else (threshold - left_ic) / (right_ic - left_ic)
        estimated_duration = left_duration + (right_duration - left_duration) * fraction
        return {
            'status': 'estimated',
            'entry_delay_bars': entry_delay_bars,
            'n_horizons': len(points),
            'baseline_horizon': base_horizon,
            'baseline_seconds': _safe_round(_base_duration.total_seconds()),
            'baseline_mean_ic': _safe_round(base_ic),
            'expected_direction': int(direction),
            'n_nonpositive_oriented_points': len(nonpositive),
            'first_nonpositive_horizon': nonpositive[0][1] if nonpositive else None,
            'half_amplitude_ic': _safe_round(direction * threshold),
            'first_crossing_before_or_at_horizon': right_horizon,
            'duration': DataFreq(estimated_duration).name,
            'seconds': _safe_round(estimated_duration.total_seconds()),
            'curve_monotonic_nonincreasing': monotonic,
        }
    return {
        'status': 'not_reached',
        'entry_delay_bars': entry_delay_bars,
        'n_horizons': len(points),
        'baseline_horizon': base_horizon,
        'baseline_seconds': _safe_round(_base_duration.total_seconds()),
        'baseline_mean_ic': _safe_round(base_ic),
        'expected_direction': int(direction),
        'n_nonpositive_oriented_points': len(nonpositive),
        'first_nonpositive_horizon': nonpositive[0][1] if nonpositive else None,
        'last_horizon': points[-1][1],
        'curve_monotonic_nonincreasing': monotonic,
    }


def _forward_ic_half_life_exponential(
    stats_by_horizon: Dict[str, Dict[int, pd.Series]], entry_delay_bars: int,
) -> dict:
    """Fit a fast continuous predictive-decay half-life on horizon means."""

    points: list[tuple[float, str, float]] = []
    for horizon, by_delay in stats_by_horizon.items():
        stats = by_delay.get(entry_delay_bars)
        mean = (
            stats.get('mean_ic', stats.get('mean'))
            if isinstance(stats, pd.Series) else None
        )
        try:
            mean_value = float(mean)
            duration = DataFreq(horizon).value
        except Exception:
            continue
        if duration > pd.Timedelta(0) and np.isfinite(mean_value):
            points.append((duration.total_seconds(), horizon, mean_value))
    result = fit_forward_ic_half_life(points, entry_delay_bars=entry_delay_bars)
    seconds = result.get('half_life_seconds')
    if seconds is not None:
        try:
            result['duration'] = DataFreq(pd.Timedelta(seconds=float(seconds))).name
        except Exception:
            result['duration'] = None
    return result


def _extract_product_names(*tables: pd.DataFrame | None) -> List[str]:
    names: List[str] = []
    seen: set[str] = set()
    for table in tables:
        if not isinstance(table, pd.DataFrame) or table.empty:
            continue
        for col in table.columns:
            c_name = str(getattr(col, 'name', col))
            if c_name and c_name not in seen:
                seen.add(c_name)
                names.append(c_name)
    return names


def _is_term_contract_product(product: Any) -> bool:
    marker = getattr(product, 'is_term_contract', None)
    return bool(marker()) if callable(marker) else False


def build_ic_response(
    tester: Any,
    display_columns: List[str],
    all_products: list,
    compute: Any,
    paths_hash: str,
    ic_lags: List[int],
    primary_ic_lag: int,
    ic_decay_lags: list | None,
    rolling_window: int | float | None,
    forward_horizons: List[str] | None = None,
    primary_horizons: Dict[str, str] | None = None,
    factor_refs: Dict[str, str] | None = None,
    requested_periods: Any = None,
    horizon_sampling: Dict[str, Any] | None = None,
) -> dict:
    """把 IC 中间计算结果构建为 JSON 响应 dict。"""
    forward_horizons = forward_horizons or []
    primary_horizons = primary_horizons or {}
    factor_refs = factor_refs or {}

    product_map: Dict[str, Any] = {}
    alias_map: Dict[str, Any] = {}
    for product in all_products:
        product_map[str(getattr(product, 'name', product))] = product
        alias_map[str(getattr(product, 'alias', getattr(product, 'name', product)))] = product
    resolved_products: set[Any] = set()
    resolved_seen: set[int] = set()
    for product_name in compute.selected_product_names:
        product = product_map.get(product_name) or alias_map.get(product_name)
        if product is None or id(product) in resolved_seen:
            continue
        resolved_seen.add(id(product))
        resolved_products.add(product)

    ic_stats_all = pd.DataFrame({
        col: compute.stats_by_column_lag.get(col, {}).get(primary_ic_lag, pd.Series(dtype=float))
        for col in display_columns
    }).drop(index=['acf_vals', 'temporal_support', 'temporal_support_status'], errors='ignore')
    columns = ic_stats_all.columns.tolist()
    rows = ic_stats_all.to_dict(orient='records')
    indices = ic_stats_all.index.tolist()
    for index, row in enumerate(rows):
        row['index'] = indices[index]
        for key, value in list(row.items()):
            if isinstance(value, float) and (pd.isna(value) or np.isinf(value)):
                row[key] = None

    ic_decay_results: Dict[str, List[dict]] = {}
    if isinstance(ic_decay_lags, list) and ic_decay_lags:
        for col in display_columns:
            base_ic = compute.series_by_column_lag.get(col, {}).get(primary_ic_lag, pd.Series(dtype=float)).dropna()
            decay_list: List[dict] = []
            for lag in ic_decay_lags:
                try:
                    lag_i = int(lag)
                except Exception:
                    continue
                if lag_i <= 0:
                    continue
                series = base_ic.iloc[::lag_i].dropna()
                if len(series) > 1:
                    mean = float(series.mean())
                    std = float(series.std())
                    n = len(series)
                    decay_list.append({
                        'lag': lag_i, 'mean': _safe_round(mean), 'std': _safe_round(std),
                        'ir': _safe_round(mean / std) if std else None,
                        't_stat': _safe_round(mean / (std / np.sqrt(n))) if std else None,
                        'n': n,
                    })
                else:
                    decay_list.append({'lag': lag_i, 'mean': None, 'std': None, 'ir': None, 't_stat': None, 'n': 0})
            ic_decay_results[col] = decay_list

    final_products = resolved_products if resolved_products else all_products
    shared_products = [{
        'name': str(getattr(product, 'name', product)),
        'desc': str(getattr(product, 'desc', getattr(product, 'name', product))),
        'is_term_contract': _is_term_contract_product(product),
    } for product in sorted(final_products, key=lambda item: str(getattr(item, 'alias', getattr(item, 'name', item))))]

    response: dict = {
        'success': True,
        'ic_diagnostics_schema': 'ic-diagnostics-v1',
        'ic_metric_semantics': metric_semantics_catalog(),
        'paths_hash': paths_hash,
        'ic_lags': ic_lags,
        'primary_ic_lag': primary_ic_lag,
        'entry_delay_bars': ic_lags,
        'primary_entry_delay_bars': primary_ic_lag,
        'forward_return_horizons': forward_horizons,
        'forward_horizon_sampling': {
            **(horizon_sampling or {'mode': 'unknown', 'source': 'legacy_response'}),
            'resolved_horizons': list(forward_horizons),
        },
        'primary_forward_return_horizon': primary_horizons.get(display_columns[0]) if display_columns else None,
        'ic_stats': {'columns': ['index'] + columns, 'rows': rows},
        'factors': [],
    }

    for col in display_columns:
        factor = compute.factor_by_column.get(col)
        if factor is None:
            continue
        ic_s = (
            compute.series_by_column_lag.get(col, {}).get(primary_ic_lag, pd.Series(dtype=float))
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
        )
        signal_ts = _extract_signal_index(ic_s.index) if len(ic_s) else pd.DatetimeIndex([])
        is_daily = factor.freq is not None and factor.freq.is_day_multiple()
        dates = [ts.strftime('%Y-%m-%d') for ts in signal_ts] if is_daily else cast('list[str | int]', (cast(np.ndarray, signal_ts.view(np.int64)) // 10**6).tolist())
        vals = [None if (isinstance(value, float) and (pd.isna(value) or np.isinf(value))) else value for value in ic_s.values.tolist()]

        autocorr = None
        if len(ic_s) > 2:
            try:
                cached = compute.stats_by_column_lag.get(col, {}).get(primary_ic_lag)
                acf_values = cached.get('acf_vals') if isinstance(cached, pd.Series) else None
                if isinstance(acf_values, list):
                    autocorr = [{'lag': index, 'ac': _safe_round(value)} for index, value in enumerate(acf_values[1:], start=1)]
                else:
                    # Legacy caches may not carry ``acf_vals``.  Keep the
                    # chart payload compatible without changing the named
                    # diagnostics emitted by the new path.
                    values = np.asarray(ic_s.values, dtype=float)
                    centered = values - values.mean()
                    denominator = np.dot(centered, centered)
                    nlags = min(20, max(1, len(values) // 2 - 1))
                    if denominator > 0:
                        acf_values = [1.0]
                        for lag in range(1, nlags + 1):
                            acf_values.append(float(np.dot(centered[lag:], centered[:-lag]) / denominator))
                        autocorr = [{'lag': index, 'ac': _safe_round(value)} for index, value in enumerate(acf_values[1:], start=1)]
            except Exception:
                autocorr = None

        expected_sign, expected_sign_source = expected_sign_for_factor(factor)
        temporal_support_payload = compute.temporal_support_by_column_lag.get(col, {}).get(primary_ic_lag)
        temporal_support = temporal_support_from_dict(temporal_support_payload)
        rolling_ic = None
        if isinstance(rolling_window, (int, float)) and rolling_window > 1:
            win = int(rolling_window)
            values = np.asarray(ic_s.values, dtype=float)
            if len(values) >= win:
                ts_win = signal_ts[win - 1:]
                r_dates = [ts.strftime('%Y-%m-%d') for ts in ts_win] if is_daily else cast('list[str | int]', (cast(np.ndarray, ts_win.view(np.int64)) // 10**6).tolist())
                fields = (
                    # Keep the rolling projection at the same numerical
                    # coverage as summarize_ic_series.  Metadata fields are
                    # repeated deliberately: each endpoint is independently
                    # auditable after the dense result is persisted.
                    'diagnostics_schema', 'n_signal_observations', 'mean_ic',
                    'median_ic', 'std_ic', 'std_ic_ddof', 'se_iid',
                    'ci95_iid_lower', 'ci95_iid_upper', 'mad_ic',
                    'icir_signal', 't_stat_iid', 't_stat_hac', 'se_hac',
                    'ci95_hac_lower', 'ci95_hac_upper', 'hac_lag',
                    'hac_lag_source', 'hac_lag_formula', 'hac_kernel',
                    'hac_status', 'hac_reason',
                    'hac_overlap_support_seconds',
                    'hac_overlap_support_components_seconds',
                    'effective_n_raw', 'effective_n_capped',
                    'effective_n_ratio', 'effective_n_capped_ratio',
                    'ess_exceeds_n', 'hac_lrv_to_iid_variance_ratio',
                    'expected_sign', 'expected_sign_source',
                    'direction_rate', 'direction_rate_status',
                    'positive_ic_rate', 'negative_ic_rate', 'zero_ic_rate',
                    'minimum_ic', 'maximum_ic', 'p10_ic', 'p25_ic',
                    'p50_ic', 'p75_ic', 'p90_ic', 'skew_ic',
                    'excess_kurtosis_ic', 'ic_series_acf1', 'acf_estimator',
                    'ic_series_acf_half_life_signals',
                    'ic_series_acf_half_life_status', 'ic_series_ar1_rho',
                    'ic_series_ar1_r_squared',
                    'ic_series_ar1_half_life_signals',
                    'ic_series_ar1_half_life_seconds',
                    'ic_series_ar1_half_life_status',
                    'ic_series_ar1_n_signal_pairs', 'ic_series_ar1_method',
                    'ess_definition', 't_stat_hac_reference',
                )
                rolling_values: dict[str, list[Any]] = {field: [] for field in fields}
                interval_seconds = temporal_support.signal_interval_seconds if temporal_support is not None else None
                actual_spans: list[Any] = []
                expected_spans: list[Any] = []
                coverage_spans: list[Any] = []
                for end_index in range(win - 1, len(values)):
                    start_index = end_index - win + 1
                    stats = pd.Series(summarize_ic_series(pd.Series(values[start_index:end_index + 1]), expected_sign=expected_sign, expected_sign_source=expected_sign_source, temporal_support=temporal_support))
                    for field in fields:
                        rolling_values[field].append(json_safe_diagnostic_value(stats.get(field)))
                    actual_spans.append(_safe_round((pd.Timestamp(signal_ts[end_index]) - pd.Timestamp(signal_ts[start_index])).total_seconds()))
                    expected_spans.append(_safe_round((win - 1) * interval_seconds) if interval_seconds is not None else None)
                    coverage_spans.append(_safe_round(win * interval_seconds) if interval_seconds is not None else None)
                rolling_ic = {
                    'window': win, 'rolling_k_signals': [win] * len(r_dates),
                    'span_definition': 'endpoint_elapsed', 'signal_interval_seconds': interval_seconds,
                    'actual_endpoint_span_seconds': actual_spans,
                    'expected_endpoint_span_seconds': expected_spans,
                    'expected_coverage_span_seconds': coverage_spans, 'dates': r_dates,
                    **rolling_values,
                    'mean': list(rolling_values['mean_ic']), 'ir': list(rolling_values['icir_signal']),
                }

        factor_data: Dict[str, Any] = {
            'name': factor.name, 'alias': col, 'factor_alias': factor.alias,
            'factor_ref': factor_refs.get(factor.alias), 'ic_method': compute.method_by_column.get(col, 'rank'),
            'ic_diagnostics_schema': 'ic-diagnostics-v1',
            'ic_series': {'dates': dates, 'values': vals}, 'autocorr': autocorr,
            'products': shared_products, 'primary_forward_return_horizon': primary_horizons.get(col),
            'temporal_support': temporal_support_payload,
            'period_diagnostics': period_diagnostics(ic_s, factor=factor, support=temporal_support, expected_sign=expected_sign, expected_sign_source=expected_sign_source, requested_periods=requested_periods),
        }
        if len(ic_lags) > 1:
            lag_series_list = []
            lag_stats_dict: Dict[str, Dict[str, Any]] = {}
            support_by_lag: Dict[str, dict[str, Any]] = {}
            for lag_i in ic_lags:
                lag_series = (
                    compute.series_by_column_lag.get(col, {}).get(lag_i, pd.Series(dtype=float))
                    .replace([np.inf, -np.inf], np.nan)
                    .dropna()
                )
                lag_ts = _extract_signal_index(lag_series.index) if len(lag_series) else pd.DatetimeIndex([])
                lag_dates = [ts.strftime('%Y-%m-%d') for ts in lag_ts] if is_daily else cast('list[str | int]', (cast(np.ndarray, lag_ts.view(np.int64)) // 10**6).tolist())
                lag_series_list.append({'lag': lag_i, 'dates': lag_dates, 'values': [None if (isinstance(value, float) and (pd.isna(value) or np.isinf(value))) else value for value in lag_series.values.tolist()]})
                lag_stats = compute.stats_by_column_lag.get(col, {}).get(lag_i)
                if isinstance(lag_stats, pd.Series):
                    lag_stats_dict[str(lag_i)] = serialise_stats_series(lag_stats)
                support = compute.temporal_support_by_column_lag.get(col, {}).get(lag_i)
                if isinstance(support, dict):
                    support_by_lag[str(lag_i)] = support
            factor_data['ic_series_by_lag'] = lag_series_list
            factor_data['ic_stats_by_lag'] = lag_stats_dict
            factor_data['temporal_support_by_lag'] = support_by_lag
        if ic_decay_results:
            factor_data['ic_resample_stability'] = ic_decay_results.get(col, [])
            factor_data['ic_decay'] = ic_decay_results.get(col, [])
        horizon_series_list = []
        horizon_stats: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for horizon_name in compute.series_by_column_horizon_lag.get(col, {}):
            by_lag = compute.series_by_column_horizon_lag.get(col, {}).get(horizon_name, {})
            for lag_i in ic_lags:
                series = by_lag.get(lag_i, pd.Series(dtype=float)).replace([np.inf, -np.inf], np.nan).dropna()
                timestamps = _extract_signal_index(series.index) if len(series) else pd.DatetimeIndex([])
                h_dates = [ts.strftime('%Y-%m-%d') for ts in timestamps] if is_daily else cast('list[str | int]', (cast(np.ndarray, timestamps.view(np.int64)) // 10**6).tolist())
                horizon_series_list.append({'horizon': horizon_name, 'entry_delay_bars': lag_i, 'dates': h_dates, 'values': [None if pd.isna(value) or np.isinf(value) else value for value in series.values.tolist()]})
                stats = compute.stats_by_column_horizon_lag.get(col, {}).get(horizon_name, {}).get(lag_i)
                if isinstance(stats, pd.Series):
                    horizon_stats.setdefault(horizon_name, {})[str(lag_i)] = serialise_stats_series(stats)
        factor_data['ic_series_by_forward_horizon'] = horizon_series_list
        factor_data['ic_stats_by_forward_horizon'] = horizon_stats
        half_lives = {str(lag_i): _forward_ic_half_life(compute.stats_by_column_horizon_lag.get(col, {}), lag_i) for lag_i in ic_lags}
        exponential_half_lives = {
            str(lag_i): _forward_ic_half_life_exponential(
                compute.stats_by_column_horizon_lag.get(col, {}), lag_i,
            )
            for lag_i in ic_lags
        }
        factor_data['forward_ic_half_life_by_entry_delay'] = half_lives
        factor_data['forward_ic_half_life'] = half_lives[str(primary_ic_lag)]
        factor_data['forward_ic_half_life_exponential_by_entry_delay'] = exponential_half_lives
        factor_data['forward_ic_half_life_exponential'] = exponential_half_lives[str(primary_ic_lag)]
        if rolling_ic:
            factor_data['rolling_ic'] = rolling_ic
        response['factors'].append(factor_data)

    existing = {factor.alias for factor in tester.factors}
    for factor in compute.factor_by_column.values():
        if factor.alias not in existing:
            tester.factors.append(factor)
            existing.add(factor.alias)
        else:
            for index, existing_factor in enumerate(tester.factors):
                if existing_factor.alias == factor.alias:
                    if existing_factor is not factor and hasattr(tester, 'discard_result'):
                        tester.discard_result(existing_factor)
                    tester.factors[index] = factor
                    break
    return response
