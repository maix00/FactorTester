"""IC computation for immutable research RunSpecs."""
import hashlib
import threading
import traceback
from typing import Any, Dict, List, Tuple, cast

import orjson

import numpy as np
import pandas as pd

from tools.factors import Factor
from tools.factors.FactorFamily import FactorFamily, _active_tester
from tools.factors.Parameters import FactorNextPeriodReturns
from tools.factors.tester_calc.CrossSectionIC import CrossSectionIC
from tools.factors.tester_calc.CrossSectionPearsonIC import CrossSectionPearsonIC
from tools.factors.tester_calc.NextReturns import NextReturns
from tools.factors.tester_calc.single_factor_test.ic import (
    build_ic_factor, collect_ic_result, discard_ic_factor, run_ic_for_factor,
)
from tools.data.types import DataFreq, DataTime

from server.services.eval_progress import count_nodes, setup as setup_progress, teardown as teardown_progress
from server.services.factor_registry import factor_from_alias
from server.services.session_runtime import user_obj_for_name
from server.modules.shared.factor_tester_runtime import (
    create_isolated_factor_tester_for_run,
    selection_from_request,
)


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _extract_signal_index(idx: pd.Index) -> pd.DatetimeIndex:
    if isinstance(idx, pd.MultiIndex):
        signal_name = next((n for n in idx.names if n and str(n).startswith('_SIGNAL')), None)
        level = idx.names.index(signal_name) if signal_name is not None else -1
        return pd.DatetimeIndex(idx.get_level_values(level), name=idx.names[level])
    return pd.DatetimeIndex(idx)


def _safe_round(v: Any, ndigits: int = 6) -> Any:
    if v is None:
        return None
    try:
        fv = float(v)
    except Exception:
        return None
    if np.isnan(fv) or np.isinf(fv):
        return None
    return round(fv, ndigits)


def _forward_ic_half_life(
    stats_by_horizon: Dict[str, Dict[int, pd.Series]], entry_delay_bars: int,
) -> dict:
    """Estimate the first forward-horizon IC half-amplitude crossing.

    The reference is the shortest tested horizon at this entry delay.  IC is
    oriented by its sign there, so a negative factor is handled symmetrically.
    This is a descriptive estimate of predictive decay, not the ACF half-life
    of the realised IC time series and not a recommended holding period.
    """
    points: list[tuple[pd.Timedelta, str, float]] = []
    for horizon, by_delay in stats_by_horizon.items():
        stats = by_delay.get(entry_delay_bars)
        mean = stats.get('mean') if isinstance(stats, pd.Series) else None
        try:
            mean_value = float(mean)
            duration = DataFreq(horizon).value
        except Exception:
            continue
        if duration > pd.Timedelta(0) and np.isfinite(mean_value):
            points.append((duration, horizon, mean_value))
    points.sort(key=lambda item: item[0])
    if len(points) < 2:
        return {'status': 'insufficient_horizons', 'entry_delay_bars': entry_delay_bars}

    base_duration, base_horizon, base_ic = points[0]
    if abs(base_ic) <= 1e-12:
        return {
            'status': 'zero_baseline_ic', 'entry_delay_bars': entry_delay_bars,
            'baseline_horizon': base_horizon, 'baseline_mean_ic': _safe_round(base_ic),
        }
    direction = 1.0 if base_ic > 0 else -1.0
    threshold = abs(base_ic) / 2.0
    oriented = [(duration, horizon, mean * direction) for duration, horizon, mean in points]
    monotonic = all(
        later[2] <= earlier[2] + 1e-12
        for earlier, later in zip(oriented, oriented[1:])
    )
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
            'baseline_horizon': base_horizon,
            'baseline_mean_ic': _safe_round(base_ic),
            'half_amplitude_ic': _safe_round(direction * threshold),
            'first_crossing_before_or_at_horizon': right_horizon,
            'duration': DataFreq(estimated_duration).name,
            'seconds': _safe_round(estimated_duration.total_seconds()),
            'curve_monotonic_nonincreasing': monotonic,
        }
    return {
        'status': 'not_reached',
        'entry_delay_bars': entry_delay_bars,
        'baseline_horizon': base_horizon,
        'baseline_mean_ic': _safe_round(base_ic),
        'last_horizon': points[-1][1],
        'curve_monotonic_nonincreasing': monotonic,
    }


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
    if callable(marker):
        return bool(marker())
    return False


# ═══════════════════════════════════════════════════════════════
# 参数解析（共享）
# ═══════════════════════════════════════════════════════════════

def _run_window_datetimes(
    settings: dict[str, Any] | None,
) -> tuple[DataTime | None, DataTime | None]:
    if not settings:
        return None, None
    start_date = str(settings.get("start_date") or "").strip()
    end_date = str(settings.get("end_date") or "").strip()
    if not start_date or not end_date:
        return None, None
    precision = str(settings.get("time_precision") or "exact")
    if precision == "trading_day":
        return (
            DataTime(ts=pd.Timestamp(start_date), precision="trading_day"),
            DataTime(ts=pd.Timestamp(end_date), precision="trading_day"),
        )
    timezone = str(settings.get("timezone") or "Asia/Shanghai")
    start_time = str(settings.get("start_time") or "00:00")
    end_time = str(settings.get("end_time") or "23:59")
    start = pd.Timestamp(f"{start_date} {start_time}").tz_localize(timezone)
    end = pd.Timestamp(f"{end_date} {end_time}").tz_localize(timezone)
    return DataTime(ts=start, precision="exact"), DataTime(ts=end, precision="exact")


def _forward_horizon_bases(data: dict, errors: List[str]) -> tuple[List[str], List[int]]:
    """Parse physical forward-return horizons.

    ``$F`` is a signal sampling interval, not a return horizon.  ``signal`` is
    therefore a convenient *base* which expands separately for every factor.
    Explicit bases (for example ``1m`` or ``1d``) are expanded in parallel and
    deduplicated by their physical duration.
    """
    raw = data.get('forward_return_horizons')
    if raw is None:
        # The old UI stored this but the runtime never consumed it.  Preserve
        # its intended one-period meaning during migration.
        legacy_mode = str(data.get('return_frequency_mode') or 'factor_frequency')
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


def _resolve_forward_horizons(signal_freq: DataFreq, bases: List[str], multipliers: List[int]) -> List[DataFreq]:
    """Expand bases for one signal frequency, retaining stable request order."""
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


def _parse_ic_params(data: dict) -> Tuple[
    str,                    # product_path_selection_id
    str,                    # factor_family_alias
    List[dict],             # factor_alias_return_freq
    List[str],              # paths
    list | None,            # ic_decay_lags
    int | float | None,     # rolling_window
    List[int],              # ic_lags
    int,                    # primary_ic_lag
    str,                    # ic_correlation
    FactorNextPeriodReturns, # returns column
    List[str],              # forward horizon bases
    List[int],              # forward horizon multipliers
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

    factor_alias_return_freq = data.get('factors', [])
    factor_family_alias = str(data.get('factor_family_alias') or '')
    if not factor_family_alias and not factor_alias_return_freq:
        errors.append('缺少 factors')
    paths = data.get('paths', [])
    ic_decay_lags = data.get('ic_decay_lags', None)
    rolling_window = data.get('rolling_window', None)
    settings = data.get('settings') if isinstance(data.get('settings'), dict) else {}
    data_source = str(settings.get('data_source') or '').strip()
    frequency = str(settings.get('frequency') or '').strip()
    if data_source and data_source != 'auto':
        errors.append(f'当前 IC 测试不支持数据源 {data_source}，请使用自动')
    if frequency and frequency != 'auto':
        errors.append(f'当前 IC 测试不支持数据频率 {frequency}，请使用自动')
    ic_correlation = str(data.get('ic_correlation') or settings.get('ic_correlation') or 'rank')
    if ic_correlation not in ('rank', 'pearson', 'both'):
        errors.append(f'ic_correlation 非法: {ic_correlation}')

    return_price_basis = str(data.get('return_price_basis') or settings.get('return_price_basis') or 'next_open_to_open_adjusted')
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
        ic_lags_raw
        if isinstance(ic_lags_raw, list)
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

    forward_horizon_bases, forward_horizon_multipliers = _forward_horizon_bases(data, errors)

    if errors:
        raise ValueError('; '.join(errors))

    return (
        product_path_selection_id, factor_family_alias, factor_alias_return_freq,
        paths, ic_decay_lags, rolling_window, ic_lags, ic_lags[0],
        ic_correlation, returns_col, forward_horizon_bases, forward_horizon_multipliers,
    )


# ═══════════════════════════════════════════════════════════════
# IC 计算状态容器
# ═══════════════════════════════════════════════════════════════

class _ICComputeResult:
    """IC 计算结果的中间状态。"""
    def __init__(self):
        self.series_by_column_lag: Dict[str, Dict[int, pd.Series]] = {}
        self.stats_by_column_lag: Dict[str, Dict[int, pd.Series]] = {}
        self.series_by_column_horizon_lag: Dict[str, Dict[str, Dict[int, pd.Series]]] = {}
        self.stats_by_column_horizon_lag: Dict[str, Dict[str, Dict[int, pd.Series]]] = {}
        self.primary_horizon_by_column: Dict[str, str] = {}
        self.factor_by_column: Dict[str, Factor] = {}
        self.method_by_column: Dict[str, str] = {}
        self.selected_product_names: List[str] = []


class _ICCancelled(RuntimeError):
    """Raised when an async IC job has been cancelled."""


def _merge_ic_result(
    compute: _ICComputeResult,
    key: tuple,
    result: Tuple,
    tester: Any,
    primary_ic_lag: int,
    primary_horizons: Dict[str, str],
):
    """将一组 IC 结果合并到 compute 中。"""
    horizon_name = str(key[-4])
    lag_i = int(key[-3])
    method = str(key[-2])
    display_alias = str(key[-1])
    primary_horizon = primary_horizons[display_alias]
    factor_list, ic_series, stats, re_table, fe_table, data_present_mask = result
    for factor in factor_list:
        compute.series_by_column_horizon_lag.setdefault(display_alias, {}).setdefault(horizon_name, {})[lag_i] = ic_series.copy()
        compute.stats_by_column_horizon_lag.setdefault(display_alias, {}).setdefault(horizon_name, {})[lag_i] = stats.copy()
        if horizon_name == primary_horizon:
            compute.series_by_column_lag.setdefault(display_alias, {})[lag_i] = ic_series.copy()
            compute.stats_by_column_lag.setdefault(display_alias, {})[lag_i] = stats.copy()
        compute.factor_by_column[display_alias] = factor
        compute.method_by_column[display_alias] = method
        if horizon_name == primary_horizon and lag_i == primary_ic_lag:
            r = tester._get_result(factor)
            r.ic_series = ic_series.copy()
            r.ic_stats = stats.copy()
            if not re_table.empty:
                r.returns = re_table
            if not fe_table.empty:
                r.func_table = fe_table
            if not data_present_mask.empty:
                r.data_present_mask = data_present_mask.copy(deep=False)
                r.data_present_all = bool(data_present_mask.to_numpy(dtype=bool).all())
            p_names = _extract_product_names(fe_table, re_table)
            if p_names:
                for p_name in p_names:
                    if p_name not in compute.selected_product_names:
                        compute.selected_product_names.append(p_name)


# ═══════════════════════════════════════════════════════════════
# IC 分组计算（共享：被 JSON 和 SSE 两个端点复用）
# ═══════════════════════════════════════════════════════════════

def _compute_ic_groups(
    tester: Any,
    param_items: List[Tuple[tuple, List[Factor]]],
    param_payloads: Dict[tuple, Dict[str, Any]],
    primary_ic_lag: int,
    primary_horizons: Dict[str, str],
    *,
    emitter: Any | None = None,
    cancel_event: threading.Event | None = None,
) -> _ICComputeResult:
    """执行 IC 分组计算（支持并行）。返回中间状态。"""
    state = _ICComputeResult()

    def _check_cancelled() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise _ICCancelled("IC test job cancelled")

    total_groups = len(param_items)

    # ── node-level 进度统计 ──
    if emitter is not None:
        total_nodes = 0
        from tools.factors.tester_calc import CrossSectionIC as _CSI
        for key, _ in param_items:
            payload = param_payloads[key]
            fe_param = payload.get('FE')
            if fe_param is not None and hasattr(fe_param, '_expr'):
                total_nodes += count_nodes(fe_param._expr)
            # Private (`_`-prefixed) keys carry method metadata, not factor-family
            # params — strip them and use the per-method family class, mirroring
            # run_ic_for_factor().
            ic_family_cls = payload.get('_ic_family_cls') or _CSI
            clean_payload = {k: v for k, v in payload.items() if not str(k).startswith('_')}
            tmp = ic_family_cls().get_factor(**clean_payload)
            if hasattr(tmp, '_expr'):
                total_nodes += count_nodes(tmp._expr)
        setup_progress(total_nodes, lambda c, t: emitter.emit_progress(c, t, 'eval'))
        emitter.emit_start(total=total_nodes, groups=total_groups, phase='init')

    try:
        # All roots in one source-frequency partition share the same products,
        # run window and preload.  Evaluate them serially inside a batch so
        # structurally identical FE subtrees can use one run-scoped cache.
        # Roots without an explicit source frequency retain the old isolated
        # path because their compatible context cannot be asserted safely.
        from collections import defaultdict
        from tools.factors.evaluation import evaluate_factors

        batch_partitions: Dict[str, list[tuple[tuple, List[Factor], Factor, Any]]] = defaultdict(list)
        fallback_items: list[Tuple[tuple, List[Factor]]] = []
        for key, factor_list in param_items:
            _check_cancelled()
            ic_factor, source_freq = build_ic_factor(param_payloads[key], factor_list)
            if source_freq is None:
                discard_ic_factor(tester, ic_factor)
                fallback_items.append((key, factor_list))
            else:
                batch_partitions[source_freq.name].append((key, factor_list, ic_factor, source_freq))

        group_done = 0
        for partition in batch_partitions.values():
            _check_cancelled()
            roots = [item[2] for item in partition]
            try:
                evaluate_factors(
                    roots, products=tester.products, freq=partition[0][3],
                    start_dt=tester.start_dt, end_dt=tester.end_dt,
                )
                for key, factor_list, ic_factor, _source_freq in partition:
                    result = collect_ic_result(tester, ic_factor, factor_list)
                    group_done += 1
                    if emitter is not None:
                        emitter.emit_progress(group_done, total_groups, 'group_done')
                    _merge_ic_result(state, key, result, tester, primary_ic_lag, primary_horizons)
            finally:
                for _key, _factor_list, ic_factor, _source_freq in partition:
                    discard_ic_factor(tester, ic_factor)

        # This branch is expected only for legacy factors that do not declare
        # a source frequency.  It keeps old inference behaviour intact.
        for key, factor_list in fallback_items:
            _check_cancelled()
            result = run_ic_for_factor(tester, param_payloads[key], factor_list)
            group_done += 1
            if emitter is not None:
                emitter.emit_progress(group_done, total_groups, 'group_done')
            _merge_ic_result(state, key, result, tester, primary_ic_lag, primary_horizons)
    finally:
        if emitter is not None:
            teardown_progress()

    return state


# ═══════════════════════════════════════════════════════════════
# 结果构建（共享：把中间状态转为 JSON dict）
# ═══════════════════════════════════════════════════════════════

def _build_ic_response(
    tester: Any,
    display_columns: List[str],
    all_products: list,
    compute: _ICComputeResult,
    paths_hash: str,
    ic_lags: List[int],
    primary_ic_lag: int,
    ic_decay_lags: list | None,
    rolling_window: int | float | None,
    forward_horizons: List[str] | None = None,
    primary_horizons: Dict[str, str] | None = None,
) -> dict:
    """把 IC 中间计算结果构建为 JSON 响应 dict。"""
    forward_horizons = forward_horizons or []
    primary_horizons = primary_horizons or {}

    # ── 产品过滤 ──
    product_map: Dict[str, Any] = {}
    alias_map: Dict[str, Any] = {}
    for p in all_products:
        p_name = str(getattr(p, 'name', p))
        p_alias = str(getattr(p, 'alias', p_name))
        product_map[p_name] = p
        alias_map[p_alias] = p

    resolved_products: set[Any] = set()
    resolved_seen: set[int] = set()
    for p_name in compute.selected_product_names:
        p_obj = product_map.get(p_name) or alias_map.get(p_name)
        if p_obj is None:
            continue
        obj_id = id(p_obj)
        if obj_id in resolved_seen:
            continue
        resolved_seen.add(obj_id)
        resolved_products.add(p_obj)

    # ── IC stats 表 ──
    ic_stats_all = pd.DataFrame({
        col: compute.stats_by_column_lag.get(col, {}).get(primary_ic_lag, pd.Series(dtype=float))
        for col in display_columns
    })
    # 排除内部传递的 acf_vals（仅用于前端 autocorr 复用，不展示在 stats 表）
    ic_stats_all = ic_stats_all.drop(index='acf_vals', errors='ignore')
    columns = ic_stats_all.columns.tolist()
    rows = ic_stats_all.to_dict(orient='records')
    indices = ic_stats_all.index.tolist()
    for i, row in enumerate(rows):
        row['index'] = indices[i]
        for k, v in list(row.items()):
            if isinstance(v, float) and (pd.isna(v) or np.isinf(v)):
                row[k] = None

    # ── IC decay ──
    ic_decay_results: Dict[str, List[dict]] = {}
    if isinstance(ic_decay_lags, list) and len(ic_decay_lags) > 0:
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
                s = base_ic.iloc[::lag_i].dropna()
                if len(s) > 1:
                    mean_val = float(s.mean())
                    std_val = float(s.std())
                    ir_val = (mean_val / std_val) if std_val != 0 else None
                    n_val = len(s)
                    t_val = (mean_val / (std_val / np.sqrt(n_val))) if std_val != 0 and n_val > 1 else None
                    decay_list.append({
                        'lag': lag_i, 'mean': _safe_round(mean_val), 'std': _safe_round(std_val),
                        'ir': _safe_round(ir_val), 't_stat': _safe_round(t_val), 'n': n_val,
                    })
                else:
                    decay_list.append({
                        'lag': lag_i, 'mean': None, 'std': None,
                        'ir': None, 't_stat': None, 'n': 0,
                    })
            ic_decay_results[col] = decay_list

    # ── products 列表 — 所有因子共享，提到循环外只构建一次 ──
    final_products = resolved_products if resolved_products else all_products
    shared_products: List[dict] = []
    for p in sorted(final_products, key=lambda p: str(getattr(p, 'alias', getattr(p, 'name', p)))):
        p_name = str(getattr(p, 'name', p))
        p_desc = str(getattr(p, 'desc', p_name))
        shared_products.append({
            'name': p_name, 'desc': p_desc,
            'is_term_contract': _is_term_contract_product(p),
        })

    response: dict = {
        'success': True,
        'paths_hash': paths_hash,
        'ic_lags': ic_lags,
        'primary_ic_lag': primary_ic_lag,
        'entry_delay_bars': ic_lags,
        'primary_entry_delay_bars': primary_ic_lag,
        'forward_return_horizons': forward_horizons,
        'primary_forward_return_horizon': primary_horizons.get(display_columns[0]) if display_columns else None,
        'ic_stats': {'columns': ['index'] + columns, 'rows': rows},
        'factors': [],
    }

    for col in display_columns:
        factor = compute.factor_by_column.get(col)
        if factor is None:
            continue
        ic_s = compute.series_by_column_lag.get(col, {}).get(primary_ic_lag, pd.Series(dtype=float)).dropna()
        signal_ts = _extract_signal_index(ic_s.index) if len(ic_s) > 0 else pd.DatetimeIndex([])
        is_daily = factor.freq is not None and factor.freq.is_day_multiple()
        if is_daily:
            dates = [ts.strftime('%Y-%m-%d') for ts in signal_ts]
        else:
            raw = cast(np.ndarray, signal_ts.view(np.int64))
            dates = cast('list[str | int]', (raw // 10**6).tolist())
        vals = [None if (isinstance(v, float) and (pd.isna(v) or np.isinf(v))) else v
                for v in ic_s.values.tolist()]

        # autocorr — 优先复用 ic_stats() 已算好的 acf_vals，避免重复调用 statsmodels
        autocorr = None
        if len(ic_s) > 2:
            try:
                cached_stats = compute.stats_by_column_lag.get(col, {}).get(primary_ic_lag)
                acf_vals_list = cached_stats.get('acf_vals') if isinstance(cached_stats, pd.Series) else None
                if acf_vals_list is not None and isinstance(acf_vals_list, list):
                    autocorr = [{'lag': i, 'ac': _safe_round(v)} for i, v in enumerate(acf_vals_list[1:], start=1)]
                else:
                    # 回退路径（旧缓存没有 acf_vals 时）
                    s_vals = np.asarray(ic_s.values, dtype=float)
                    s_centered = s_vals - s_vals.mean()
                    denom = np.dot(s_centered, s_centered)
                    nlags = min(20, max(1, len(s_vals) // 2 - 1))
                    if denom > 0:
                        acf_arr = [1.0]
                        for lag in range(1, nlags + 1):
                            num = np.dot(s_centered[lag:], s_centered[:-lag])
                            acf_arr.append(float(num / denom))
                        autocorr = [{'lag': i, 'ac': _safe_round(v)} for i, v in enumerate(acf_arr[1:], start=1)]
            except Exception:
                autocorr = None

        # rolling_ic — pandas 向量化替代 Python for 循环
        rolling_ic = None
        if isinstance(rolling_window, (int, float)) and rolling_window > 1:
            win = int(rolling_window)
            s_vals = np.asarray(ic_s.values, dtype=float)
            if len(s_vals) >= win:
                s = pd.Series(s_vals)
                r_mean = s.rolling(win, min_periods=win).mean().iloc[win - 1:].to_numpy(dtype=float)
                r_std = s.rolling(win, min_periods=win).std(ddof=1).iloc[win - 1:].to_numpy(dtype=float)
                r_ir = np.full_like(r_mean, np.nan)
                valid_mask = r_std > 0
                r_ir[valid_mask] = r_mean[valid_mask] / r_std[valid_mask]
                ts_win = signal_ts[win - 1:]
                if is_daily:
                    r_dates = [ts.strftime('%Y-%m-%d') for ts in ts_win]
                else:
                    r_dates = cast('list[str | int]', (cast(np.ndarray, ts_win.view(np.int64)) // 10**6).tolist())
                rolling_ic = {
                    'window': win,
                    'dates': r_dates,
                    'mean': [_safe_round(float(v)) if not np.isnan(v) else None for v in r_mean],
                    'ir': [_safe_round(float(v)) if not np.isnan(v) else None for v in r_ir],
                }

        factor_data: Dict[str, Any] = {
            'name': factor.name,
            'alias': col,
            'factor_alias': factor.alias,
            'ic_method': compute.method_by_column.get(col, 'rank'),
            'ic_series': {'dates': dates, 'values': vals},
            'autocorr': autocorr,
            'products': shared_products,
            'primary_forward_return_horizon': primary_horizons.get(col),
        }

        # multi-lag
        if len(ic_lags) > 1:
            lag_series_list = []
            lag_stats_dict: Dict[str, Dict[str, Any]] = {}
            for lag_i in ic_lags:
                lag_series = (
                    compute.series_by_column_lag.get(col, {}).get(lag_i, pd.Series(dtype=float)).dropna()
                )
                lag_ts = (
                    _extract_signal_index(lag_series.index)
                    if len(lag_series) > 0 else pd.DatetimeIndex([])
                )
                if is_daily:
                    lag_dates = [ts.strftime('%Y-%m-%d') for ts in lag_ts]
                else:
                    raw = cast(np.ndarray, lag_ts.view(np.int64))
                    lag_dates = cast('list[str | int]', (raw // 10**6).tolist())
                lag_vals = [
                    None if (isinstance(v, float) and (pd.isna(v) or np.isinf(v))) else v
                    for v in lag_series.values.tolist()
                ]
                lag_series_list.append({'lag': lag_i, 'dates': lag_dates, 'values': lag_vals})
                lag_stat_s = compute.stats_by_column_lag.get(col, {}).get(lag_i)
                if isinstance(lag_stat_s, pd.Series):
                    lag_stats_dict[str(lag_i)] = {
                        str(k): _safe_round(v) for k, v in lag_stat_s.to_dict().items()
                    }
            factor_data['ic_series_by_lag'] = lag_series_list
            factor_data['ic_stats_by_lag'] = lag_stats_dict
        if ic_decay_results:
            # Sampling every Nth realised IC observation tests stability under
            # resampling; it is not a forward-return/alpha decay curve.
            factor_data['ic_resample_stability'] = ic_decay_results.get(col, [])
            factor_data['ic_decay'] = ic_decay_results.get(col, [])  # deprecated compatibility alias
        horizon_series_list = []
        horizon_stats: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for horizon_name in compute.series_by_column_horizon_lag.get(col, {}):
            by_lag = compute.series_by_column_horizon_lag.get(col, {}).get(horizon_name, {})
            for lag_i in ic_lags:
                series = by_lag.get(lag_i, pd.Series(dtype=float)).dropna()
                ts = _extract_signal_index(series.index) if len(series) else pd.DatetimeIndex([])
                h_dates = [t.strftime('%Y-%m-%d') for t in ts] if is_daily else cast('list[str | int]', (cast(np.ndarray, ts.view(np.int64)) // 10**6).tolist())
                horizon_series_list.append({
                    'horizon': horizon_name, 'entry_delay_bars': lag_i,
                    'dates': h_dates,
                    'values': [None if pd.isna(v) or np.isinf(v) else v for v in series.values.tolist()],
                })
                stat = compute.stats_by_column_horizon_lag.get(col, {}).get(horizon_name, {}).get(lag_i)
                if isinstance(stat, pd.Series):
                    horizon_stats.setdefault(horizon_name, {})[str(lag_i)] = {
                        str(k): _safe_round(v) for k, v in stat.to_dict().items()
                    }
        factor_data['ic_series_by_forward_horizon'] = horizon_series_list
        factor_data['ic_stats_by_forward_horizon'] = horizon_stats
        half_lives = {
            str(lag_i): _forward_ic_half_life(
                compute.stats_by_column_horizon_lag.get(col, {}), lag_i,
            )
            for lag_i in ic_lags
        }
        factor_data['forward_ic_half_life_by_entry_delay'] = half_lives
        factor_data['forward_ic_half_life'] = half_lives[str(primary_ic_lag)]
        if rolling_ic:
            factor_data['rolling_ic'] = rolling_ic

        response['factors'].append(factor_data)

    # sync factors to tester
    existing = {f.alias for f in tester.factors}
    for f in compute.factor_by_column.values():
        if f.alias not in existing:
            tester.factors.append(f)
            existing.add(f.alias)
        else:
            for i, ef in enumerate(tester.factors):
                if ef.alias == f.alias:
                    if ef is not f and hasattr(tester, 'discard_result'):
                        tester.discard_result(ef)
                    tester.factors[i] = f
                    break

    return response


# ═══════════════════════════════════════════════════════════════
# IC 计算核心（共享预处理 + 调度）
# ═══════════════════════════════════════════════════════════════

def _prepare_ic_compute(
    data: dict,
    tester: Any,
    factor_family: Any,
) -> Tuple[
    List[str],              # display columns
    str,                    # paths_hash
    list,                   # all_products
    Dict[tuple, List[Factor]],  # ic_param_map
    Dict[tuple, Dict[str, Any]], # param_payloads
    list | None,            # ic_decay_lags
    int | float | None,     # rolling_window
    List[int],              # ic_lags
    int,                    # primary_ic_lag
    List[str],              # forward_horizons
    Dict[str, str],         # primary_forward_horizon by display column
]:
    """解析参数并构建 IC 分组映射。"""
    (product_path_selection_id, _, factor_alias_return_freq, paths, ic_decay_lags, rolling_window,
     ic_lags, primary_ic_lag, ic_correlation, returns_col,
     forward_horizon_bases, forward_horizon_multipliers) = _parse_ic_params(data)

    paths_hash_source = paths if paths else [product_path_selection_id]
    paths_hash = hashlib.md5(str(sorted(paths_hash_source)).encode()).hexdigest()

    matched_factors: List[Factor] = []
    for item in factor_alias_return_freq:
        f = factor_family.get_factor_by_alias(item.get('alias', ''))
        if f is not None:
            matched_factors.append(f)
    if not matched_factors:
        raise ValueError('没有找到匹配的因子，请检查收益率频率设置中的因子是否属于当前因子家族')

    all_products = tester.products.copy()

    ic_param_map: Dict[tuple, List[Factor]] = {}
    param_payloads: Dict[tuple, Dict[str, Any]] = {}
    display_columns: List[str] = []
    forward_horizons: List[str] = []
    primary_horizons: Dict[str, str] = {}

    shift = 0 if returns_col.value.name.startswith('OPEN') else 1

    next_returns_family = NextReturns()
    methods = ['rank', 'pearson'] if ic_correlation == 'both' else [ic_correlation]
    method_family = {
        'rank': CrossSectionIC,
        'pearson': CrossSectionPearsonIC,
    }
    method_label = {
        'rank': 'Rank IC',
        'pearson': 'Pearson IC',
    }
    for factor in matched_factors:
        effective_freq = factor.freq
        if effective_freq is None:
            raise ValueError(f'Factor {factor.alias}: 无法确定收益率频率')
        factor_horizons = _resolve_forward_horizons(
            effective_freq, forward_horizon_bases, forward_horizon_multipliers,
        )
        for horizon in factor_horizons:
            if horizon.name not in forward_horizons:
                forward_horizons.append(horizon.name)
        for method in methods:
            display_alias = factor.alias if len(methods) == 1 else f"{factor.alias} · {method_label[method]}"
            if display_alias not in display_columns:
                display_columns.append(display_alias)
            primary_horizons.setdefault(display_alias, factor_horizons[0].name)
            for horizon in factor_horizons:
                for lag_i in ic_lags:
                    key = (
                        str(factor._structural_key()),
                        effective_freq.name,
                        shift,
                        returns_col.value.name,
                        horizon.name,
                        lag_i,
                        method,
                        display_alias,
                    )
                    if key not in ic_param_map:
                        returns_factor = next_returns_family.get_factor(
                            SC=returns_col.value,
                            RF=horizon.value,
                            S=shift,
                            **{'$F': effective_freq.value, '$Rev': '0'},
                        )
                        ic_param_map[key] = []
                        param_payloads[key] = {
                            'FE': factor,
                            'RE': returns_factor,
                            'Lag': lag_i,
                            '$F': effective_freq.value,
                            '_ic_family_cls': method_family[method],
                            '_ic_method': method,
                        }
                    ic_param_map[key].append(factor)

    if not forward_horizons:
        raise ValueError('没有可用的 forward return horizon')
    return (
        display_columns, paths_hash, all_products, ic_param_map, param_payloads,
        ic_decay_lags, rolling_window, ic_lags, primary_ic_lag,
        forward_horizons, primary_horizons,
    )


def _run_ic_compute_to_sink(
    data: dict[str, Any],
    tester: Any,
    factor_family: FactorFamily,
    sink: Any,
    prepared: tuple | None = None,
    cancel_event: Any | None = None,
) -> None:
    _token = None
    try:
        cancel_event = cancel_event or getattr(getattr(sink, "job", None), "cancel_event", None)
        if cancel_event is not None and cancel_event.is_set():
            raise _ICCancelled("IC test job cancelled before start")

        if prepared is None:
            prepared = _prepare_ic_compute(data, tester, factor_family)
        (display_columns, paths_hash, all_products, ic_param_map, param_payloads,
         ic_decay_lags, rolling_window, ic_lags, primary_ic_lag,
         forward_horizons, primary_horizons) = prepared

        tester.sync_signal_index = None
        tester.sync_signal_index_replaced = None
        _token = _active_tester.set(tester)

        param_items = list(ic_param_map.items())

        compute = _compute_ic_groups(
            tester, param_items, param_payloads, primary_ic_lag, primary_horizons,
            emitter=sink,
            cancel_event=cancel_event,
        )
        if cancel_event is not None and cancel_event.is_set():
            raise _ICCancelled("IC test job cancelled")
        response = _build_ic_response(
            tester, display_columns, all_products, compute,
            paths_hash, ic_lags, primary_ic_lag, ic_decay_lags, rolling_window,
            forward_horizons, primary_horizons,
        )
        from server.services.external_factor_artifacts import result_metadata

        response["external_factor_artifacts"] = result_metadata(
            data.get("external_factor_artifacts")
        )
        sink.emit_result(response)
    except _ICCancelled as exc:
        sink.emit_error(str(exc), cancelled=True)
    except Exception as e:
        sink.emit_error(str(e), traceback=traceback.format_exc())
    finally:
        if _token is not None:
            _active_tester.reset(_token)


def execute_ic_run_spec(data: dict[str, Any], *, sink: Any, cancel_event: Any) -> None:
    """Execute IC from frozen paths and aliases without consulting PageRuntime."""
    owner = str(data.get("_owner") or data.get("owner_username") or "").strip()
    run_id = str(data.get("run_id") or data.get("run_token") or "").strip()
    if not owner or not run_id:
        raise ValueError("IC RunSpec requires owner and run_id")
    selection = selection_from_request(data, page_uuid="")
    settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    start_dt, end_dt = _run_window_datetimes(settings)
    tester = create_isolated_factor_tester_for_run(
        selection,
        run_id=run_id,
        start_dt=start_dt,
        end_dt=end_dt,
        user=user_obj_for_name(owner),
    )
    aliases = [
        str(item.get("alias") or "").strip()
        for item in (data.get("factors") or [])
        if isinstance(item, dict) and item.get("alias")
    ]
    from server.services.external_factor_artifacts import load_frozen_artifacts

    external = {
        factor.alias: factor
        for factor in load_frozen_artifacts(data.get("external_factor_artifacts"))
    }
    resolved = [
        external.get(alias) or factor_from_alias(alias, username=owner)
        for alias in aliases
    ]

    class _ResolvedFactorCollection:
        """Run-local lookup for independently resolved FactorExpr instances."""

        def __init__(self, factors: list[Factor]):
            self.factors = factors
            self._by_alias = {factor.alias: factor for factor in factors}

        def get_factor_by_alias(self, alias: str):
            return self._by_alias.get(alias)

    factor_collection = _ResolvedFactorCollection(resolved)
    _run_ic_compute_to_sink(
        data, tester, factor_collection, sink, cancel_event=cancel_event,
    )
