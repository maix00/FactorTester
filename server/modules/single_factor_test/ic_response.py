"""Build JSON/SSE response payloads from computed IC state."""

from __future__ import annotations

from typing import Any, Dict, List, cast

import numpy as np
import pandas as pd

from tools.data.types import DataFreq
from tools.factors.tester_calc.single_factor_test.ic_diagnostics import (
    expected_sign_for_factor,
    ic_metric_selected,
    ic_metric_selection_catalog,
    metric_semantics_catalog,
    normalize_ic_metric_selection,
)
from tools.factors.tester_calc.single_factor_test.ic_half_life import (
    fit_forward_ic_half_life,
)
from tools.factors.tester_calc.single_factor_test.quantile_portfolio import (
    DEFAULT_QUANTILE_PORTFOLIO,
    QUANTILE_PORTFOLIO_SCHEMA,
    compute_quantile_portfolio_statistics,
)
from server.modules.single_factor_test.ic_diagnostics import (
    json_safe_diagnostic_value,
    period_diagnostics,
    serialise_stats_series,
    temporal_support_from_dict,
)
from server.modules.single_factor_test.ic_rolling import (
    ROLLING_IC_SCHEMA,
    build_factor_rolling_ic,
    rolling_stability_semantics,
    RollingWindowSpec,
)


# A long intraday IC series is useful for the primary chart, but expanding all
# forward-horizon × entry-delay copies into the response multiplies the same
# timestamps and values many times.  Keep full detail for small diagnostics;
# long runs retain the primary series and every horizon/delay *statistic*.
IC_SERIES_DETAIL_MAX_POINTS = 50_000
IC_SERIES_DETAIL_MAX_TOTAL_POINTS = 200_000


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


def _signal_screening_panel(
    panel: pd.DataFrame | None,
    signal_index: pd.Index,
) -> pd.DataFrame:
    """Project an IC intermediate panel onto the factor's signal timestamps.

    ``FE``/``RE`` are retained by the IC evaluator at the source-bar
    resolution.  They must not be fed directly to the quantile screen: doing
    so repeats one daily signal over every source bar and changes both
    compounding and turnover.  A daily signal uses the final source row of
    the corresponding trading day; an intraday signal uses the latest source
    row at or before the signal timestamp (an as-of projection).

    The projection is deliberately label-based and never looks ahead.  The
    returned frame has the exact signal index supplied by the factor table,
    so factor, return and eligibility panels share one deterministic axis.
    """
    if not isinstance(panel, pd.DataFrame) or panel.empty:
        return pd.DataFrame(index=signal_index)
    target = pd.DatetimeIndex(signal_index)
    if target.empty:
        return pd.DataFrame(index=target)

    from tools.data.types.time_index import DataIndex

    frame = panel.copy(deep=False)
    raw_times = DataIndex(frame.index).finest_index
    if len(raw_times) != len(frame):
        return pd.DataFrame(index=target)
    raw_days = DataIndex(frame.index).trading_day_index()
    target_days = DataIndex.normalized_days(target)
    # Keep the source order stable; source panels are normally monotonic, but
    # sorting here also makes the as-of boundary explicit for unusual inputs.
    order = np.argsort(raw_times.asi8, kind="stable")
    raw_times = raw_times.take(order)
    raw_days = pd.Index(raw_days).take(order)
    frame = frame.iloc[order]

    target_is_daily = bool(len(target) == 0 or not bool((target != target.normalize()).any()))
    positions: list[int] = []
    if target_is_daily:
        # A trading-day key is preferable to natural-day normalization because
        # night-session bars belong to the following exchange trading day.
        last_by_day: dict[pd.Timestamp, int] = {}
        for pos, day in enumerate(raw_days):
            last_by_day[pd.Timestamp(day)] = pos
        positions = [last_by_day.get(pd.Timestamp(day), -1) for day in target_days]
    else:
        raw_ns = raw_times.asi8
        target_aligned = target
        if raw_times.tz is None and target.tz is not None:
            target_aligned = target.tz_localize(None)
        elif raw_times.tz is not None and target.tz is None:
            target_aligned = target.tz_localize(raw_times.tz)
        elif raw_times.tz is not None and target.tz is not None and raw_times.tz != target.tz:
            target_aligned = target.tz_convert(raw_times.tz)
        target_ns = target_aligned.asi8
        positions = [int(np.searchsorted(raw_ns, value, side="right") - 1) for value in target_ns]

    values = np.full((len(target), frame.shape[1]), np.nan, dtype=float)
    source_values = frame.to_numpy(dtype=float, copy=False)
    for row, pos in enumerate(positions):
        if 0 <= pos < len(frame):
            values[row, :] = source_values[pos, :]
    return pd.DataFrame(values, index=target, columns=frame.columns)


def _series_detail_budget(
    series_by_horizon_lag: dict[str, dict[int, pd.Series]],
    series_by_lag: dict[int, pd.Series],
) -> dict[str, Any]:
    """Decide whether repeated IC-series detail is safe to materialize."""
    counts: list[int] = []
    for by_lag in series_by_horizon_lag.values():
        for series in by_lag.values():
            if isinstance(series, pd.Series):
                counts.append(int(series.replace([np.inf, -np.inf], np.nan).count()))
    for series in series_by_lag.values():
        if isinstance(series, pd.Series):
            counts.append(int(series.replace([np.inf, -np.inf], np.nan).count()))
    total = sum(counts)
    maximum = max(counts, default=0)
    full = (
        maximum <= IC_SERIES_DETAIL_MAX_POINTS
        and total <= IC_SERIES_DETAIL_MAX_TOTAL_POINTS
    )
    return {
        "status": "full" if full else "primary_only",
        "candidate_series_count": len(counts),
        "candidate_total_points": total,
        "candidate_max_points": maximum,
        "max_points_per_series": IC_SERIES_DETAIL_MAX_POINTS,
        "max_total_points": IC_SERIES_DETAIL_MAX_TOTAL_POINTS,
    }


def _is_term_contract_product(product: Any) -> bool:
    marker = getattr(product, 'is_term_contract', None)
    return bool(marker()) if callable(marker) else False


def _product_rate(product: Any, field: str, default: float) -> float:
    """Read a static screening rate, keeping non-margin products at 1.0."""
    if field == "margin" and not bool(getattr(product, "is_margin_traded", False)):
        return 1.0
    getter = getattr(product, {
        "margin": "get_long_margin_ratio",
        "open_fee": "get_open_ratio",
        "close_fee": "get_close_ratio",
    }.get(field, ""), None)
    value = getter(default) if callable(getter) else getattr(product, {
        "margin": "long_margin_ratio",
        "open_fee": "open_ratio",
        "close_fee": "close_ratio",
    }.get(field, ""), default)
    try:
        value = float(value)
    except (TypeError, ValueError):
        return float(default)
    return value if np.isfinite(value) and value >= 0 else float(default)


def _rate_vector(
    columns: list[Any], products: list[Any], config: dict[str, Any],
    key: str, field: str, default: float,
) -> np.ndarray:
    product_map = {
        str(getattr(product, "name", product)): product for product in products
    }
    product_map.update({
        str(getattr(product, "alias", getattr(product, "name", product))): product
        for product in products
    })
    overrides = config.get(key)
    if isinstance(overrides, dict):
        values = [overrides.get(str(column), None) for column in columns]
    elif isinstance(overrides, (list, tuple)):
        values = list(overrides)
    else:
        values = [None] * len(columns)
    result = []
    for index, column in enumerate(columns):
        product = product_map.get(str(getattr(column, "name", column)))
        override = values[index] if index < len(values) else None
        if field == "margin" and product is not None and not bool(
            getattr(product, "is_margin_traded", False)
        ):
            result.append(1.0)
            continue
        if override is not None:
            try:
                result.append(float(override))
                continue
            except (TypeError, ValueError):
                pass
        result.append(_product_rate(product, field, default) if product is not None else default)
    return np.asarray(result, dtype=float)


def _quick_portfolio_statistics(
    tester: Any, factor: Any, products: list[Any], config: dict[str, Any],
    *, factor_panel: pd.DataFrame | None = None,
    forward_panel: pd.DataFrame | None = None,
    eligibility: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Build the screening category from one realized factor/return panel."""
    if not isinstance(config, dict):
        config = {}
    if not bool(config.get("enabled", True)):
        return {"schema_version": QUANTILE_PORTFOLIO_SCHEMA, "status": "disabled"}
    try:
        result = None
        if factor_panel is None or forward_panel is None or eligibility is None:
            result = tester._get_result(factor)
        factor_panel = factor_panel if factor_panel is not None else getattr(result, "func_table", None)
        forward_panel = forward_panel if forward_panel is not None else getattr(result, "returns", None)
        eligibility = eligibility if eligibility is not None else getattr(result, "data_present_mask", None)
        if not isinstance(factor_panel, pd.DataFrame) or factor_panel.empty:
            return {"schema_version": QUANTILE_PORTFOLIO_SCHEMA, "status": "source_unavailable"}
        if not isinstance(forward_panel, pd.DataFrame) or forward_panel.empty:
            return {"schema_version": QUANTILE_PORTFOLIO_SCHEMA, "status": "source_unavailable"}
        # IC intermediates are evaluated at the source-bar frequency while the
        # factor itself is aligned to its declared signal frequency.  Project
        # every panel onto that signal axis before ranking/compounding; using
        # the raw source panel would repeat a daily signal over every minute
        # and silently change both return and turnover semantics.
        signal_table = None
        try:
            signal_table = getattr(factor, "table", None)
        except (AttributeError, KeyError, TypeError, ValueError):
            signal_table = None
        if isinstance(signal_table, pd.DataFrame) and not signal_table.empty:
            from tools.data.types.time_index import DataIndex

            signal_index = DataIndex(signal_table.index).signal_index
            # The factor table is already the authoritative, signal-aligned
            # factor value.  Only the return label and availability mask need
            # a source-bar → signal-time projection.
            factor_panel = signal_table
            forward_panel = _signal_screening_panel(forward_panel, signal_index)
            if isinstance(eligibility, pd.DataFrame):
                eligibility = _signal_screening_panel(eligibility, signal_index)
        if factor_panel.empty or forward_panel.empty:
            return {"schema_version": QUANTILE_PORTFOLIO_SCHEMA, "status": "source_unavailable"}
        settings = {**DEFAULT_QUANTILE_PORTFOLIO, **config}
        columns = [str(getattr(column, "name", column)) for column in factor_panel.columns]
        margin = _rate_vector(columns, products, settings, "margin_rates", "margin", 1.0)
        opening = _rate_vector(columns, products, settings, "open_fee_rates", "open_fee", 0.0)
        closing = _rate_vector(columns, products, settings, "close_fee_rates", "close_fee", 0.0)
        output = compute_quantile_portfolio_statistics(
            factor_panel,
            forward_panel,
            group_count=int(settings.get("group_count", 5)),
            eligibility=eligibility if isinstance(eligibility, pd.DataFrame) else None,
            margin_rates=margin,
            open_fee_rates=opening,
            close_fee_rates=closing,
            modes=tuple(settings.get("modes", DEFAULT_QUANTILE_PORTFOLIO["modes"])),
            target_margin_utilization=float(settings.get("target_margin_utilization", 0.30)),
            initial_capital=float(settings.get("initial_capital", 1.0)),
            include_return_series=bool(settings.get("include_return_series", False)),
        )
        output["status"] = "computed"
        output["source_scope"] = "primary_forward_return_panel"
        output["fee_semantics"] = "proportional_open_close_rates; fixed-currency fees omitted"
        output["margin_semantics"] = "non-margin products use margin rate 1.0"
        output["metric_semantics"] = output.get("metric_semantics") or []
        return output
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        return {
            "schema_version": QUANTILE_PORTFOLIO_SCHEMA,
            "status": "source_invalid",
            "reason": str(exc),
        }


def _quantile_statistics_for_factor(
    compute: Any,
    column: str,
    factor: Any,
    tester: Any,
    products: list[Any],
    config: dict[str, Any],
    primary_horizon: str | None,
    primary_lag: int,
) -> dict[str, Any]:
    """Return primary quick stats plus compact stats for every horizon/delay."""
    by_factor = getattr(compute, "quantile_portfolio_statistics_by_column_horizon_lag", {}) or {}
    by_horizon = by_factor.get(column) or {}
    primary = (by_horizon.get(str(primary_horizon or ""), {}) or {}).get(primary_lag)
    if not isinstance(primary, dict):
        primary = _quick_portfolio_statistics(tester, factor, products, config)
    if not isinstance(primary, dict):
        primary = {"schema_version": QUANTILE_PORTFOLIO_SCHEMA, "status": "source_unavailable"}
    output = dict(primary)
    if output.get("status") == "computed":
        output["source_scope"] = "primary_forward_return_panel"
        output["source_scope_definition"] = (
            "factor-declared primary horizon and entry delay"
        )
    horizon_payload: dict[str, dict[str, dict[str, Any]]] = {}
    for horizon, by_lag in by_horizon.items():
        if not isinstance(by_lag, dict):
            continue
        entries = {
            str(lag): value for lag, value in by_lag.items()
            if isinstance(value, dict)
        }
        if entries:
            horizon_payload[str(horizon)] = entries
    if horizon_payload:
        output["by_forward_horizon"] = horizon_payload
    return output


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
    metric_selection: Dict[str, Any] | None = None,
    rolling_window_specs: list[RollingWindowSpec] | None = None,
    quantile_portfolio_config: Dict[str, Any] | None = None,
) -> dict:
    """把 IC 中间计算结果构建为 JSON 响应 dict。"""
    forward_horizons = forward_horizons or []
    primary_horizons = primary_horizons or {}
    factor_refs = factor_refs or {}
    metric_selection = normalize_ic_metric_selection(metric_selection)
    quantile_portfolio_config = (
        dict(quantile_portfolio_config)
        if isinstance(quantile_portfolio_config, dict) else {}
    )
    if rolling_window_specs is None and isinstance(rolling_window, (int, float)) and rolling_window > 1:
        rolling_window_specs = [
            RollingWindowSpec("signals", int(rolling_window), f"K={int(rolling_window)}")
        ]
    rolling_window_specs = rolling_window_specs or []

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
    if metric_selection.get("mode") != "all":
        selected_indices = set(metric_selection.get("resolved") or ())
        if any(
            str(name).startswith("forward_ic_half_life")
            for name in selected_indices
        ):
            # Keep the scalar dependency used by the horizon-level fit.
            selected_indices.add("mean_ic")
        ic_stats_all = ic_stats_all.loc[
            [index for index in ic_stats_all.index if str(index) in selected_indices]
        ]
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
        'ic_statistics_schema': 'ic-statistics-v2',
        'ic_statistics_categories': {
            'correlation': 'cross-sectional IC correlation and inference',
            'rolling_stability': 'rolling-window stability of the realised IC series',
            'period_diagnostics': 'calendar-period estimability and IC diagnostics',
            'forward_horizon_half_life': 'forward-horizon predictive-decay diagnostics',
            'quantile_portfolio_statistics': (
                'vectorized grouped-return screening; not an event backtest'
            ),
        },
        'ic_statistics_category_semantics': {
            'correlation': {
                'scope': 'signal-level and horizon-level cross-sectional IC',
                'unit': 'IC / inference statistics',
            },
            'rolling_stability': {
                'scope': 'dependent rolling windows over the realised IC sequence',
                'unit': 'IC statistics and stability ratios',
            },
            'period_diagnostics': {
                'scope': 'calendar-period blocks',
                'unit': 'estimability status and IC statistics',
            },
            'forward_horizon_half_life': {
                'scope': 'horizon-level predictive decay',
                'unit': 'duration',
            },
            'quantile_portfolio_statistics': {
                'scope': 'vectorized grouped-return screening',
                'unit': 'return metrics and decimal target-weight turnover proxy',
                'event_backtest_equivalent': False,
                'source_scope': 'primary row uses the factor-declared panel; by_forward_horizon rows use their realized panel',
                'source_scope_definition': (
                    'primary row: factor-declared horizon and entry delay; '
                    'non-primary rows: realized factor forward-return panel for that horizon and entry delay'
                ),
            },
        },
        'ic_metric_semantics': metric_semantics_catalog(),
        'ic_metric_selection': metric_selection,
        'ic_metric_selection_catalog': ic_metric_selection_catalog(),
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
        'rolling_ic_schema': ROLLING_IC_SCHEMA,
        'rolling_window_specs': [spec.to_dict() for spec in rolling_window_specs],
        'rolling_stability_semantics': rolling_stability_semantics(),
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
        temporal_support_by_horizon_lag = getattr(
            compute, "temporal_support_by_column_horizon_lag", {},
        ) or {}
        rolling_support = temporal_support_by_horizon_lag.get(col, {})
        if not rolling_support and temporal_support_payload is not None:
            fallback_horizon = primary_horizons.get(col) or next(
                iter(compute.series_by_column_horizon_lag.get(col, {})), ""
            )
            rolling_support = {
                str(fallback_horizon): {primary_ic_lag: temporal_support_payload}
            }
        rolling_ic = build_factor_rolling_ic(
            factor=factor,
            series_by_horizon_lag=compute.series_by_column_horizon_lag.get(col, {}),
            support_by_horizon_lag=rolling_support,
            primary_horizon=primary_horizons.get(col),
            primary_lag=primary_ic_lag,
            window_specs=rolling_window_specs,
            metric_selection=metric_selection,
        )

        series_detail = _series_detail_budget(
            compute.series_by_column_horizon_lag.get(col, {}) or {},
            compute.series_by_column_lag.get(col, {}) or {},
        )
        series_detail.update({
            "primary_points": int(len(ic_s)),
            "omitted_series_count": max(
                0,
                int(series_detail["candidate_series_count"]) - 1,
            ),
            "omitted_total_points": max(
                0,
                int(series_detail["candidate_total_points"]) - int(len(ic_s)),
            ),
            "scope": (
                "primary ic_series only; all forward-horizon and entry-delay "
                "statistics remain complete"
                if series_detail["status"] == "primary_only"
                else "all realised horizon and entry-delay series"
            ),
        })

        period_payload = period_diagnostics(
            ic_s,
            factor=factor,
            support=temporal_support,
            expected_sign=expected_sign,
            expected_sign_source=expected_sign_source,
            requested_periods=requested_periods,
            metric_selection=metric_selection,
        )
        factor_data: Dict[str, Any] = {
            'name': factor.name, 'alias': col, 'factor_alias': factor.alias,
            'factor_ref': factor_refs.get(factor.alias), 'ic_method': compute.method_by_column.get(col, 'rank'),
            'primary_entry_delay_bars': int(primary_ic_lag),
            'ic_diagnostics_schema': 'ic-diagnostics-v1',
            'ic_series': {'dates': dates, 'values': vals}, 'autocorr': autocorr,
            'products': shared_products, 'primary_forward_return_horizon': primary_horizons.get(col),
            'ic_series_detail': series_detail,
            'temporal_support': temporal_support_payload,
            'period_diagnostics': period_payload,
            'ic_statistics': {
                'schema_version': 'ic-statistics-v2',
                'period_diagnostics': period_payload,
                'correlation': {
                    'primary': serialise_stats_series(
                        compute.stats_by_column_lag.get(col, {}).get(primary_ic_lag, pd.Series(dtype=float)),
                        metric_selection,
                    ),
                },
            'quantile_portfolio_statistics': _quantile_statistics_for_factor(
                compute, col, factor, tester, all_products,
                quantile_portfolio_config, primary_horizons.get(col), primary_ic_lag,
            ),
            },
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
                if series_detail["status"] == "full":
                    lag_ts = _extract_signal_index(lag_series.index) if len(lag_series) else pd.DatetimeIndex([])
                    lag_dates = [ts.strftime('%Y-%m-%d') for ts in lag_ts] if is_daily else cast('list[str | int]', (cast(np.ndarray, lag_ts.view(np.int64)) // 10**6).tolist())
                    lag_series_list.append({'lag': lag_i, 'dates': lag_dates, 'values': [None if (isinstance(value, float) and (pd.isna(value) or np.isinf(value))) else value for value in lag_series.values.tolist()]})
                lag_stats = compute.stats_by_column_lag.get(col, {}).get(lag_i)
                if isinstance(lag_stats, pd.Series):
                    lag_stats_dict[str(lag_i)] = serialise_stats_series(lag_stats, metric_selection)
                support = compute.temporal_support_by_column_lag.get(col, {}).get(lag_i)
                if isinstance(support, dict):
                    support_by_lag[str(lag_i)] = support
            if series_detail["status"] == "full":
                factor_data['ic_series_by_lag'] = lag_series_list
            factor_data['ic_stats_by_lag'] = lag_stats_dict
            factor_data['temporal_support_by_lag'] = support_by_lag
        # Keep the legacy top-level fields, while exposing the same objects in
        # the structured category namespace for new consumers.
        factor_data['ic_statistics']['period_diagnostics'] = factor_data['period_diagnostics']
        if ic_decay_results:
            factor_data['ic_resample_stability'] = ic_decay_results.get(col, [])
            factor_data['ic_decay'] = ic_decay_results.get(col, [])
            factor_data['ic_statistics']['resample_stability'] = ic_decay_results.get(col, [])
        horizon_series_list = []
        horizon_stats: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for horizon_name in compute.series_by_column_horizon_lag.get(col, {}):
            by_lag = compute.series_by_column_horizon_lag.get(col, {}).get(horizon_name, {})
            for lag_i in ic_lags:
                series = by_lag.get(lag_i, pd.Series(dtype=float)).replace([np.inf, -np.inf], np.nan).dropna()
                if series_detail["status"] == "full":
                    timestamps = _extract_signal_index(series.index) if len(series) else pd.DatetimeIndex([])
                    h_dates = [ts.strftime('%Y-%m-%d') for ts in timestamps] if is_daily else cast('list[str | int]', (cast(np.ndarray, timestamps.view(np.int64)) // 10**6).tolist())
                    horizon_series_list.append({'horizon': horizon_name, 'entry_delay_bars': lag_i, 'dates': h_dates, 'values': [None if pd.isna(value) or np.isinf(value) else value for value in series.values.tolist()]})
                stats = compute.stats_by_column_horizon_lag.get(col, {}).get(horizon_name, {}).get(lag_i)
                if isinstance(stats, pd.Series):
                    horizon_stats.setdefault(horizon_name, {})[str(lag_i)] = serialise_stats_series(stats, metric_selection)
        if series_detail["status"] == "full":
            factor_data['ic_series_by_forward_horizon'] = horizon_series_list
        factor_data['ic_stats_by_forward_horizon'] = horizon_stats
        factor_data['ic_statistics']['correlation']['by_forward_horizon'] = horizon_stats
        if (
            ic_metric_selected(metric_selection, 'forward_ic_half_life')
            or ic_metric_selected(metric_selection, 'forward_ic_half_life_exponential')
        ):
            half_lives = {
                str(lag_i): _forward_ic_half_life(
                    compute.stats_by_column_horizon_lag.get(col, {}), lag_i,
                )
                for lag_i in ic_lags
            }
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
            factor_data['ic_statistics']['forward_horizon_half_life'] = {
                'crossing': half_lives,
                'exponential': exponential_half_lives,
            }
        if rolling_ic:
            factor_data['rolling_ic'] = rolling_ic
            factor_data['rolling_ic_stability'] = rolling_ic.get('stability_summary', [])
            factor_data['ic_statistics']['rolling_stability'] = rolling_ic
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
