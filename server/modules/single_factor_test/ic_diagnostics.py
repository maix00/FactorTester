"""Server-side serialization and period diagnostics for IC results.

The numerical definitions live in
``tools.factors.tester_calc.single_factor_test.ic_diagnostics``.  This module
owns response shaping only: explicit field names, configurable calendar
blocks, and JSON-safe values shared by the JSON and SSE IC endpoints.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tools.factors.temporal_support import TemporalSupport
from tools.factors.tester_calc.single_factor_test.ic_diagnostics import (
    filter_ic_metric_mapping,
    summarize_ic_series,
)


_NON_TABLE_STATS = {'acf_vals', 'temporal_support', 'temporal_support_status'}


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


def json_safe_diagnostic_value(value: Any, ndigits: int = 6) -> Any:
    """Convert one diagnostic value to a JSON-safe, readable scalar/tree."""
    if value is None:
        return None
    if isinstance(value, (np.integer, np.floating)):
        value = value.item()
    if isinstance(value, (list, tuple)):
        return [json_safe_diagnostic_value(item, ndigits) for item in value]
    if isinstance(value, dict):
        return {
            str(key): json_safe_diagnostic_value(item, ndigits)
            for key, item in value.items()
        }
    if isinstance(value, bool) or isinstance(value, str) or isinstance(value, int):
        return value
    if isinstance(value, float):
        return _safe_round(value, ndigits)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def serialise_stats_series(
    stats: pd.Series | None,
    metric_selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize diagnostics, excluding internal ACF/support payloads."""
    if not isinstance(stats, pd.Series):
        return {}
    payload = {
        str(key): json_safe_diagnostic_value(value)
        for key, value in stats.to_dict().items()
        if str(key) not in _NON_TABLE_STATS
    }
    return filter_ic_metric_mapping(payload, metric_selection)


def temporal_support_from_dict(payload: Any) -> TemporalSupport | None:
    """Rehydrate the immutable support contract for rolling/period diagnostics."""
    if not isinstance(payload, dict):
        return None
    sources = payload.get('sources') if isinstance(payload.get('sources'), dict) else {}
    try:
        return TemporalSupport.from_components(
            factor_input_support_seconds=payload.get('factor_input_support_seconds'),
            signal_interval_seconds=payload.get('signal_interval_seconds'),
            label_horizon_seconds=payload.get('label_horizon_seconds'),
            holding_support_seconds=payload.get('holding_support_seconds'),
            decay_support_seconds=payload.get('decay_support_seconds'),
            factor_input_source=str(sources.get('factor_input_support') or 'response'),
            signal_interval_source=str(sources.get('signal_interval') or 'response'),
            label_horizon_source=str(sources.get('label_horizon') or 'response'),
            holding_support_source=str(sources.get('holding_support') or 'response'),
            decay_support_source=str(sources.get('decay_support') or 'response'),
            notes=payload.get('notes') or (),
        )
    except (TypeError, ValueError):
        return None


def _extract_signal_index(idx: pd.Index) -> pd.DatetimeIndex:
    if isinstance(idx, pd.MultiIndex):
        signal_name = next(
            (name for name in idx.names if name and str(name).startswith('_SIGNAL')),
            None,
        )
        level = idx.names.index(signal_name) if signal_name is not None else -1
        return pd.DatetimeIndex(idx.get_level_values(level), name=idx.names[level])
    return pd.DatetimeIndex(idx)


def _period_key(timestamp: pd.Timestamp, rule: str) -> pd.Timestamp:
    """Resolve a configurable calendar period without using factor aliases."""
    normalized = str(rule).strip().lower()
    if normalized in {'hour', 'h', '1h'}:
        return timestamp.floor('h')
    if normalized in {'day', 'd', '1d'}:
        return timestamp.normalize()
    if normalized in {'week', 'w', '1w'}:
        return timestamp.to_period('W').start_time
    if normalized in {'month', 'm', '1m'}:
        return timestamp.to_period('M').start_time
    if normalized in {'quarter', 'q', '1q'}:
        return timestamp.to_period('Q').start_time
    raise ValueError(f'unsupported IC period rule: {rule}')


def _default_period_specs(factor: Any) -> list[dict[str, Any]]:
    """Use hour/day blocks for intraday signals and calendar blocks for daily ones."""
    freq = getattr(factor, 'freq', None)
    try:
        is_daily = bool(freq is not None and freq.is_day_multiple())
    except Exception:
        is_daily = False
    rules = ('day', 'week', 'month', 'quarter') if is_daily else ('hour', 'day', 'week')
    return [
        {'label': rule, 'rule': rule, 'min_signal_observations': 2, 'min_periods': 3}
        for rule in rules
    ]


def _period_specs(raw: Any, factor: Any) -> list[dict[str, Any]]:
    """Normalize optional ``ic_periods`` request; defaults remain frequency-aware."""
    values = raw if isinstance(raw, list) else _default_period_specs(factor)
    specs: list[dict[str, Any]] = []
    for item in values:
        if isinstance(item, str):
            item = {'label': item, 'rule': item}
        if not isinstance(item, dict):
            continue
        rule = str(item.get('rule') or item.get('label') or '').strip()
        if not rule:
            continue
        try:
            _period_key(pd.Timestamp('2024-01-01'), rule)
        except ValueError:
            continue
        try:
            min_signals = max(1, int(item.get('min_signal_observations', 2)))
        except (TypeError, ValueError):
            min_signals = 2
        try:
            min_periods = max(1, int(item.get('min_periods', 3)))
        except (TypeError, ValueError):
            min_periods = 3
        specs.append({
            'label': str(item.get('label') or rule),
            'rule': rule,
            'min_signal_observations': min_signals,
            'min_periods': min_periods,
        })
    return specs


def period_diagnostics(
    ic_series: pd.Series,
    *,
    factor: Any,
    support: TemporalSupport | None,
    expected_sign: int | None,
    expected_sign_source: str | None,
    requested_periods: Any = None,
    metric_selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return per-period IC summaries plus separate estimability states."""
    if not isinstance(ic_series, pd.Series) or ic_series.empty:
        return {'schema': 'ic-period-diagnostics-v1', 'periods': {}}
    timestamps = _extract_signal_index(ic_series.index)
    values = list(ic_series.values)
    output: dict[str, Any] = {}
    for spec in _period_specs(requested_periods, factor):
        grouped: dict[pd.Timestamp, list[Any]] = {}
        for timestamp, value in zip(timestamps, values):
            try:
                key = _period_key(pd.Timestamp(timestamp), spec['rule'])
            except ValueError:
                continue
            grouped.setdefault(key, []).append(value)
        records: list[dict[str, Any]] = []
        estimable_count = 0
        hac_count = 0
        for period_start, period_values in sorted(grouped.items()):
            stats = pd.Series(summarize_ic_series(
                pd.Series(period_values),
                expected_sign=expected_sign,
                expected_sign_source=expected_sign_source,
                temporal_support=support,
            ))
            n_signals = int(stats.get('n_signal_observations') or 0)
            period_estimable = n_signals >= spec['min_signal_observations']
            hac_estimable = stats.get('hac_status') == 'estimable'
            estimable_count += int(period_estimable)
            hac_count += int(period_estimable and hac_estimable)
            record = serialise_stats_series(stats, metric_selection)
            record.update({
                'period_start': period_start.isoformat(),
                'period_rule': spec['rule'],
                'period_estimable': period_estimable,
                'hac_estimable': hac_estimable,
            })
            records.append(record)
        output[spec['label']] = {
            'rule': spec['rule'],
            'min_signal_observations': spec['min_signal_observations'],
            'min_periods': spec['min_periods'],
            'n_periods_total': len(records),
            'n_periods_estimable': estimable_count,
            'n_periods_hac_estimable': hac_count,
            'period_estimability_status': (
                'estimable' if estimable_count >= spec['min_periods'] else 'not_estimable'
            ),
            'periods': records,
        }
    return {'schema': 'ic-period-diagnostics-v1', 'periods': output}
