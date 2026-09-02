"""Request parsing and forward-horizon expansion for IC jobs."""

from __future__ import annotations

from typing import Any, List, Tuple

import pandas as pd

from tools.data.types import DataFreq, DataTime
from tools.factors.Parameters import FactorNextPeriodReturns
from tools.factors.tester_calc.single_factor_test.ic_diagnostics import (
    normalize_ic_metric_selection,
)
from server.modules.single_factor_test.ic_rolling_params import (
    normalize_rolling_window_specs,
)
from server.modules.shared.factor_tester_runtime import require_run_window


# Reserved request marker.  It is never sent to ``FactorNextPeriodReturns``;
# ``resolve_forward_horizons`` expands it into physical, scale-aware points
# after the factor's actual signal interval is known.
SCALE_AWARE_HORIZON_BASE = "__scale_aware__"


def _scale_aware_horizon_durations(signal_freq: DataFreq) -> list[DataFreq]:
    """Return a compact horizon grid appropriate for one signal interval.

    The grid is dense near the signal interval (where a short-lived factor is
    expected to decay) and grows approximately geometrically.  Sub-daily
    factors also receive 1d/2d/3d/5d tail points so an intraday signal is not
    mistaken for a purely intraday effect.  All values are physical durations,
    so a 1-minute and a 5-minute factor receive proportional grids.
    """

    signal_seconds = float(signal_freq.value.total_seconds())
    minute = 60.0
    hour = 60.0 * minute
    day = 24.0 * hour
    if signal_seconds <= 5.0 * minute:
        multipliers = (1, 2, 3, 5, 10, 15, 30, 60, 120, 240, 480)
    elif signal_seconds <= 30.0 * minute:
        multipliers = (1, 2, 3, 5, 10, 15, 30, 60, 120)
    elif signal_seconds < day:
        multipliers = (1, 2, 3, 5, 10, 15, 30, 60)
    elif signal_seconds == day:
        multipliers = (1, 2, 3, 5, 10, 20)
    else:
        multipliers = (1, 2, 3, 5, 10)

    durations = [signal_freq.value * multiple for multiple in multipliers]
    if signal_seconds < day:
        durations.extend(pd.Timedelta(days=multiple) for multiple in (1, 2, 3, 5))
    unique = sorted({duration for duration in durations if duration > pd.Timedelta(0)})
    return [DataFreq(duration) for duration in unique]


def run_window_datetimes(
    configuration: dict | None,
) -> tuple[DataTime, DataTime]:
    if not configuration:
        return require_run_window(None, None)
    start_date = str(configuration.get("start_date") or "").strip()
    end_date = str(configuration.get("end_date") or "").strip()
    if not start_date or not end_date:
        return require_run_window(
            start_date or None,
            end_date or None,
        )
    precision = str(configuration.get("time_precision") or "exact")
    if precision == "trading_day":
        return require_run_window(
            DataTime(ts=pd.Timestamp(start_date), precision="trading_day"),
            DataTime(ts=pd.Timestamp(end_date), precision="trading_day"),
        )
    timezone = str(configuration.get("timezone") or "Asia/Shanghai")
    start_time = str(configuration.get("start_time") or "00:00")
    end_time = str(configuration.get("end_time") or "23:59")
    start = pd.Timestamp(f"{start_date} {start_time}").tz_localize(timezone)
    end = pd.Timestamp(f"{end_date} {end_time}").tz_localize(timezone)
    return require_run_window(
        DataTime(ts=start, precision="exact"),
        DataTime(ts=end, precision="exact"),
    )


def parse_forward_horizon_bases(data: dict, errors: List[str]) -> tuple[List[str], List[int]]:
    """Parse physical forward-return horizons.

    ``$F`` is a signal sampling interval, not a return horizon.  ``signal`` is
    therefore a convenient base which expands separately for every factor.
    Explicit bases (for example ``1m`` or ``1d``) are expanded in parallel and
    deduplicated by their physical duration.  Direct requests that omit both
    ``forward_return_horizons`` and the legacy ``return_frequency_mode`` use a
    scale-aware grid; callers can request the same preset explicitly with
    ``{"sampling": "scale_aware"}``.
    """
    raw = data.get('forward_return_horizons')
    if raw is None:
        # Direct RunSpec callers often omit the legacy UI setting.  Use the
        # scale-aware grid in that case; an explicitly supplied legacy mode
        # retains its historical single-horizon behaviour.
        legacy_mode_raw = data.get('return_frequency_mode')
        if legacy_mode_raw is None:
            return [SCALE_AWARE_HORIZON_BASE], [1]
        legacy_mode = str(legacy_mode_raw or 'factor_frequency')
        legacy_base = {
            'factor_frequency': 'signal',
            'daily': '1d',
            'minute': '1m',
        }.get(legacy_mode)
        if legacy_base is None:
            errors.append(f'return_frequency_mode 非法: {legacy_mode}')
            legacy_base = 'signal'
        return [legacy_base], [1]
    if not isinstance(raw, dict):
        errors.append('forward_return_horizons 必须是对象')
        return ['signal'], [1]
    sampling = str(raw.get('sampling') or '').strip().lower()
    if sampling in {'scale_aware', 'auto'}:
        return [SCALE_AWARE_HORIZON_BASE], [1]
    if sampling not in {'', 'explicit', 'legacy'}:
        errors.append('forward_return_horizons.sampling 必须是 explicit 或 scale_aware')
        sampling = 'explicit'
    bases = raw.get('bases', ['signal'])
    multipliers = raw.get('multipliers', [1])
    if not isinstance(bases, list) or not bases:
        errors.append('forward_return_horizons.bases 必须是非空数组')
        bases = ['signal']
    if not isinstance(multipliers, list) or not multipliers:
        errors.append('forward_return_horizons.multipliers 必须是非空数组')
        multipliers = [1]
    normalized_bases: List[str] = []
    for raw_base in bases:
        base = str(raw_base).strip()
        if base == 'signal':
            normalized_bases.append(base)
            continue
        try:
            if DataFreq(base).value <= pd.Timedelta(0):
                raise ValueError
        except Exception:
            errors.append(f'forward_return_horizons.bases 非法: {raw_base}')
            continue
        normalized_bases.append(base)
    normalized_multipliers: List[int] = []
    for raw_multiple in multipliers:
        try:
            multiple = int(raw_multiple)
        except (TypeError, ValueError):
            errors.append(f'forward_return_horizons.multipliers 非法: {raw_multiple}')
            continue
        if multiple <= 0:
            errors.append('forward_return_horizons.multipliers 必须为正整数')
            continue
        if multiple not in normalized_multipliers:
            normalized_multipliers.append(multiple)
    return normalized_bases or ['signal'], normalized_multipliers or [1]


def describe_forward_horizon_sampling(data: dict) -> dict[str, object]:
    """Describe the requested horizon policy for an auditable response."""

    raw = data.get('forward_return_horizons')
    if raw is None:
        if data.get('return_frequency_mode') is None:
            return {'mode': 'scale_aware', 'source': 'default_direct_request'}
        return {
            'mode': 'legacy', 'source': 'return_frequency_mode',
            'return_frequency_mode': str(data.get('return_frequency_mode')),
        }
    if isinstance(raw, dict):
        sampling = str(raw.get('sampling') or '').strip().lower()
        if sampling in {'scale_aware', 'auto'}:
            return {'mode': 'scale_aware', 'source': 'request'}
        return {
            'mode': 'explicit', 'source': 'request',
            'bases': list(raw.get('bases') or ['signal']),
            'multipliers': list(raw.get('multipliers') or [1]),
        }
    return {'mode': 'invalid', 'source': 'request'}


def resolve_forward_horizons(
    signal_freq: DataFreq, bases: List[str], multipliers: List[int],
) -> List[DataFreq]:
    """Expand bases for one signal frequency, retaining stable request order."""
    if SCALE_AWARE_HORIZON_BASE in bases:
        return _scale_aware_horizon_durations(signal_freq)
    values: List[DataFreq] = []
    seen: set[pd.Timedelta] = set()
    for base in bases:
        base_freq = signal_freq if base == 'signal' else DataFreq(base)
        for multiple in multipliers:
            horizon = DataFreq(base_freq.value * multiple)
            if horizon.value not in seen:
                seen.add(horizon.value)
                values.append(horizon)
    return values


def parse_ic_params(data: dict) -> Tuple[
    str, str, List[dict], List[str], list | None, Any,
    List[int], int, str, FactorNextPeriodReturns, List[str], List[int],
]:
    """从 request JSON 中解析所有 IC 测试参数并校验。"""
    errors: List[str] = []
    product_path_selection = data.get('product_path_selection')
    product_path_selection_id = str(data.get('product_path_selection_id') or '')
    if isinstance(product_path_selection, dict):
        product_path_selection_id = str(
            product_path_selection.get('product_path_selection_id')
            or product_path_selection.get('selection_id')
            or product_path_selection.get('id')
            or product_path_selection_id
        )
    if not product_path_selection_id:
        errors.append('缺少 product_path_selection_id')

    factor_items = data.get('factors', [])
    factor_family_alias = str(data.get('factor_family_alias') or '')
    if not factor_family_alias and not factor_items:
        errors.append('缺少 factors')
    paths = data.get('paths', [])
    ic_decay_lags = data.get('ic_decay_lags', None)
    # Keep the scalar field only for legacy tuple callers.  The execution
    # path normalizes rolling_windows into per-factor window specs.
    rolling_window = data.get('rolling_window', None)
    try:
        normalize_ic_metric_selection(data.get('ic_metric_selection'))
    except ValueError as exc:
        errors.append(str(exc))
    try:
        normalize_rolling_window_specs(data)
    except ValueError as exc:
        errors.append(str(exc))
    data_source = str(data.get('data_source') or '').strip()
    frequency = str(data.get('frequency') or '').strip()
    if data_source and data_source != 'auto':
        errors.append(f'当前 IC 测试不支持数据源 {data_source}，请使用自动')
    if frequency and frequency != 'auto':
        errors.append(f'当前 IC 测试不支持数据频率 {frequency}，请使用自动')
    ic_correlation = str(data.get('ic_correlation') or 'rank')
    if ic_correlation not in ('rank', 'pearson', 'both'):
        errors.append(f'ic_correlation 非法: {ic_correlation}')

    return_price_basis = str(data.get('return_price_basis') or 'next_open_to_open_adjusted')
    returns_col_map = {
        'next_open_to_open': FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN,
        'next_open_to_open_adjusted': FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED,
        'next_close_to_close': FactorNextPeriodReturns.THIS_CLOSE_TO_CLOSE,
        'next_close_to_close_adjusted': FactorNextPeriodReturns.THIS_CLOSE_TO_CLOSE_ADJUSTED,
    }
    returns_col = returns_col_map.get(return_price_basis)
    if returns_col is None:
        errors.append(f'return_price_basis 非法: {return_price_basis}')
        returns_col = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED

    ic_lag_raw = data.get('ic_lag', data.get('lag', 0))
    ic_lags_raw = data.get('ic_lags', None)
    raw_lags = (
        ic_lags_raw if isinstance(ic_lags_raw, list)
        else [ic_lags_raw] if ic_lags_raw is not None else [ic_lag_raw]
    )
    ic_lags: List[int] = []
    for raw in raw_lags:
        try:
            lag_i = int(raw)
        except (TypeError, ValueError):
            errors.append(f'ic_lag 非法: {raw}，必须是整数')
            continue
        if lag_i < 0:
            errors.append('ic_lag 不能小于 0')
            continue
        if lag_i not in ic_lags:
            ic_lags.append(lag_i)
    if not ic_lags:
        ic_lags = [0]

    forward_horizon_bases, forward_horizon_multipliers = parse_forward_horizon_bases(data, errors)
    if errors:
        raise ValueError('; '.join(errors))
    return (
        product_path_selection_id, factor_family_alias, factor_items,
        paths, ic_decay_lags, rolling_window, ic_lags, ic_lags[0],
        ic_correlation, returns_col, forward_horizon_bases, forward_horizon_multipliers,
    )
