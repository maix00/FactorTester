"""
IC test endpoints: /run_ic_test  (JSON) 和 /run_ic_test_stream  (SSE)
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import threading
import traceback
from typing import Any, Dict, List, Tuple, cast

import orjson

import numpy as np
import pandas as pd
from flask import Response, jsonify, request

from tools.factors import Factor
from tools.factors.FactorFamily import FactorFamily, _active_tester
from tools.factors.Parameters import FactorNextPeriodReturns
from tools.factors.tests.NextReturns import NextReturns
from tools.factors.tests.single_factor_test.ic import run_ic_for_factor

from . import sft_bp
from server.services.eval_progress import count_nodes, setup as setup_progress, teardown as teardown_progress
from server.services.factor_registry import get_factor_family_instance
from server.services.page_runtime import get_factor_tester
from server.services.session_runtime import get_session_params
from server.services.sse_progress import SSEProgressEmitter


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

def _parse_ic_params(data: dict) -> Tuple[
    str,                    # submission_id
    str,                    # factor_family_alias
    List[dict],             # factor_alias_return_freq
    List[str],              # paths
    list | None,            # ic_decay_lags
    int | float | None,     # rolling_window
    List[int],              # ic_lags
    int,                    # primary_ic_lag
]:
    """从 request JSON 中解析所有 IC 测试参数并校验。"""
    errors: List[str] = []

    submission_id = str(data.get('submission_id') or '')
    if not submission_id:
        errors.append('缺少 submission_id')

    factor_family_alias = str(data.get('factor_family_alias') or '')
    if not factor_family_alias:
        errors.append('缺少 factor_family_alias')

    factor_alias_return_freq = data.get('factors', [])
    paths = data.get('paths', [])
    ic_decay_lags = data.get('ic_decay_lags', None)
    rolling_window = data.get('rolling_window', None)

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

    if errors:
        raise ValueError('; '.join(errors))

    return (
        submission_id, factor_family_alias, factor_alias_return_freq,
        paths, ic_decay_lags, rolling_window, ic_lags, ic_lags[0],
    )


# ═══════════════════════════════════════════════════════════════
# IC 计算状态容器
# ═══════════════════════════════════════════════════════════════

class _ICComputeResult:
    """IC 计算结果的中间状态。"""
    def __init__(self):
        self.series_by_factor_lag: Dict[Factor, Dict[int, pd.Series]] = {}
        self.stats_by_factor_lag: Dict[Factor, Dict[int, pd.Series]] = {}
        self.selected_product_names: List[str] = []


def _merge_ic_result(
    compute: _ICComputeResult,
    key: tuple,
    result: Tuple,
    tester: Any,
    primary_ic_lag: int,
):
    """将一组 IC 结果合并到 compute 中。"""
    lag_i = int(key[-1])
    factor_list, ic_series, stats, re_table, fe_table, data_present_mask = result
    for factor in factor_list:
        compute.series_by_factor_lag.setdefault(factor, {})[lag_i] = ic_series.copy()
        compute.stats_by_factor_lag.setdefault(factor, {})[lag_i] = stats.copy()
        if lag_i == primary_ic_lag:
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
    *,
    emitter: SSEProgressEmitter | None = None,
) -> _ICComputeResult:
    """执行 IC 分组计算（支持并行）。返回中间状态。"""
    state = _ICComputeResult()

    def _calc_one_group(item: Tuple[tuple, List[Factor]]):
        key, factor_list = item
        result = run_ic_for_factor(tester, param_payloads[key], factor_list)
        return key, result

    import settings as Settings
    total_groups = len(param_items)
    use_parallel = (
        getattr(Settings, 'IC_PARALLEL', True)
        and total_groups > 1
    )

    # ── node-level 进度统计 ──
    if emitter is not None:
        total_nodes = 0
        from tools.factors.tests import CrossSectionIC as _CSI
        for key, _ in param_items:
            fe_param = param_payloads[key].get('FE')
            if fe_param is not None and hasattr(fe_param, '_expr'):
                total_nodes += count_nodes(fe_param._expr)
            tmp = _CSI().get_factor(**param_payloads[key])
            if hasattr(tmp, '_expr'):
                total_nodes += count_nodes(tmp._expr)
        setup_progress(total_nodes, lambda c, t: emitter.emit_progress(c, t, 'eval'))
        emitter.emit_start(total=total_nodes, groups=total_groups, phase='init')

    try:
        if use_parallel:
            token = _active_tester.get()
            max_workers = min(
                getattr(Settings, 'IC_PARALLEL_MAX_WORKERS', 8),
                total_groups,
            )

            def _worker(item):
                _active_tester.set(token)
                return _calc_one_group(item)

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {pool.submit(_worker, item): item for item in param_items}
                group_done = 0
                for future in as_completed(futures):
                    key, result = future.result()
                    group_done += 1
                    if emitter is not None:
                        emitter.emit_progress(group_done, total_groups, 'group_done')
                    _merge_ic_result(state, key, result, tester, primary_ic_lag)
        else:
            group_done = 0
            for key, factor_list in param_items:
                key, result = _calc_one_group((key, factor_list))
                group_done += 1
                if emitter is not None:
                    emitter.emit_progress(group_done, total_groups, 'group_done')
                _merge_ic_result(state, key, result, tester, primary_ic_lag)
    finally:
        if emitter is not None:
            teardown_progress()

    return state


# ═══════════════════════════════════════════════════════════════
# 结果构建（共享：把中间状态转为 JSON dict）
# ═══════════════════════════════════════════════════════════════

def _build_ic_response(
    tester: Any,
    factors: List[Factor],
    all_products: list,
    compute: _ICComputeResult,
    paths_hash: str,
    ic_lags: List[int],
    primary_ic_lag: int,
    ic_decay_lags: list | None,
    rolling_window: int | float | None,
) -> dict:
    """把 IC 中间计算结果构建为 JSON 响应 dict。"""

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
        f.alias: (tester.results[f].ic_stats if f in tester.results else pd.Series(dtype=float))
        for f in factors
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
        for factor in factors:
            base_ic = (tester.results[factor].ic_series if factor in tester.results
                       else pd.Series(dtype=float)).dropna()
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
            ic_decay_results[factor.alias] = decay_list

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
        'ic_stats': {'columns': ['index'] + columns, 'rows': rows},
        'factors': [],
    }

    for factor in factors:
        ic_s = (tester.results[factor].ic_series if factor in tester.results
                else pd.Series(dtype=float)).dropna()
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
                cached_stats = tester.results[factor].ic_stats if factor in tester.results else None
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
            'alias': factor.alias,
            'ic_series': {'dates': dates, 'values': vals},
            'autocorr': autocorr,
            'products': shared_products,
        }

        # multi-lag
        if len(ic_lags) > 1:
            lag_series_list = []
            lag_stats_dict: Dict[str, Dict[str, Any]] = {}
            for lag_i in ic_lags:
                lag_series = (
                    compute.series_by_factor_lag.get(factor, {}).get(lag_i, pd.Series(dtype=float)).dropna()
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
                lag_stat_s = compute.stats_by_factor_lag.get(factor, {}).get(lag_i)
                if isinstance(lag_stat_s, pd.Series):
                    lag_stats_dict[str(lag_i)] = {
                        str(k): _safe_round(v) for k, v in lag_stat_s.to_dict().items()
                    }
            factor_data['ic_series_by_lag'] = lag_series_list
            factor_data['ic_stats_by_lag'] = lag_stats_dict
        if ic_decay_results:
            factor_data['ic_decay'] = ic_decay_results.get(factor.alias, [])
        if rolling_ic:
            factor_data['rolling_ic'] = rolling_ic

        response['factors'].append(factor_data)

    # sync factors to tester
    existing = {f.alias for f in tester.factors}
    for f in factors:
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
    all_factors: List[Factor],
) -> Tuple[
    List[Factor],           # factors
    str,                    # paths_hash
    list,                   # all_products
    Dict[tuple, List[Factor]],  # ic_param_map
    Dict[tuple, Dict[str, Any]], # param_payloads
    list | None,            # ic_decay_lags
    int | float | None,     # rolling_window
    List[int],              # ic_lags
    int,                    # primary_ic_lag
]:
    """解析参数并构建 IC 分组映射。"""
    (_, _, factor_alias_return_freq, paths, ic_decay_lags, rolling_window,
     ic_lags, primary_ic_lag) = _parse_ic_params(data)

    paths_hash = hashlib.md5(str(sorted(paths)).encode()).hexdigest()

    matched_factors: List[Factor] = []
    for item in factor_alias_return_freq:
        f = factor_family.get_factor_by_alias(item.get('alias', ''))
        if f is not None:
            matched_factors.append(f)
    if not matched_factors:
        raise ValueError('没有找到匹配的因子，请检查收益率频率设置中的因子是否属于当前因子家族')

    factors = matched_factors
    all_products = tester.products.copy()
    returns_col = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED

    ic_param_map: Dict[tuple, List[Factor]] = {}
    param_payloads: Dict[tuple, Dict[str, Any]] = {}

    shift = 0 if returns_col.value.name.startswith('OPEN') else 1

    next_returns_family = NextReturns()
    for factor in factors:
        effective_freq = factor.freq
        if effective_freq is None:
            raise ValueError(f'Factor {factor.alias}: 无法确定收益率频率')
        for lag_i in ic_lags:
            key = (
                str(factor._structural_key()),
                effective_freq.name,
                shift,
                returns_col.value.name,
                lag_i,
            )
            if key not in ic_param_map:
                returns_factor = next_returns_family.get_factor(
                    SC=returns_col.value,
                    RF=effective_freq.value,
                    S=shift,
                    **{'$F': effective_freq.value, '$Rev': '0'},
                )
                ic_param_map[key] = []
                param_payloads[key] = {
                    'FE': factor,
                    'RE': returns_factor,
                    'Lag': lag_i, '$F': effective_freq.value,
                }
            ic_param_map[key].append(factor)

    return (
        factors, paths_hash, all_products, ic_param_map, param_payloads,
        ic_decay_lags, rolling_window, ic_lags, primary_ic_lag,
    )


# ═══════════════════════════════════════════════════════════════
# 端点：JSON（兼容旧接口）
# ═══════════════════════════════════════════════════════════════

@sft_bp.route('/run_ic_test', methods=['POST'])
def run_ic_test():
    """IC 测试（JSON 一次性返回）。"""
    data = request.get_json(silent=True) or {}
    _token = None
    tester = None

    try:
        (_, _, _, _, _, _, ic_lags, primary_ic_lag) = _parse_ic_params(data)

        tester = get_factor_tester(data.get('submission_id', ''), caller='run_ic_test')
        factor_family = get_factor_family_instance(data.get('factor_family_alias', ''), username=data.get('owner_username'), page_uuid=data.get('page_uuid'))
        assert isinstance(factor_family, FactorFamily)
        session_params = get_session_params(data.get('factor_family_alias', ''), factor_family)
        all_factors = factor_family.get_factors(
            params_list=session_params,
            page_uuid=str(data.get('page_uuid') or ''),
        )

        tester.sync_signal_index = None
        tester.sync_signal_index_replaced = None
        _token = _active_tester.set(tester)

        (factors, paths_hash, all_products, ic_param_map, param_payloads,
         ic_decay_lags, rolling_window, ic_lags, primary_ic_lag) = \
            _prepare_ic_compute(data, tester, factor_family, all_factors)

        param_items = list(ic_param_map.items())

        compute = _compute_ic_groups(
            tester, param_items, param_payloads, primary_ic_lag,
        )
        response = _build_ic_response(
            tester, factors, all_products, compute,
            paths_hash, ic_lags, primary_ic_lag, ic_decay_lags, rolling_window,
        )
        return Response(orjson.dumps(response, option=orjson.OPT_SERIALIZE_NUMPY), mimetype='application/json')

    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})
    finally:
        if _token is not None:
            _active_tester.reset(_token)


# ═══════════════════════════════════════════════════════════════
# 端点：SSE 流式
# ═══════════════════════════════════════════════════════════════

@sft_bp.route('/run_ic_test_stream', methods=['POST'])
def run_ic_test_stream():
    """SSE 流式 IC 测试 — 推送进度事件 + 最终结果"""
    data = request.get_json(silent=True) or {}

    # ── 在主线程中完成所有需要 context 的操作 ──
    try:
        tester = get_factor_tester(str(data.get('submission_id', '')), caller='run_ic_test_stream')
        factor_family = get_factor_family_instance(str(data.get('factor_family_alias', '')), username=data.get('owner_username'), page_uuid=data.get('page_uuid'))
        assert isinstance(factor_family, FactorFamily)
        session_params = get_session_params(str(data.get('factor_family_alias', '')), factor_family)
        all_factors = factor_family.get_factors(
            params_list=session_params,
            page_uuid=str(data.get('page_uuid') or ''),
        )
    except Exception as e:
        def _early_err():
            yield f"event: error\ndata: {json.dumps({'success': False, 'error': str(e), 'traceback': traceback.format_exc()}, default=str)}\n\n"
        return Response(_early_err(), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    emitter = SSEProgressEmitter()

    def _compute_and_emit():
        _token = None
        try:
            (factors, paths_hash, all_products, ic_param_map, param_payloads,
             ic_decay_lags, rolling_window, ic_lags, primary_ic_lag) = \
                _prepare_ic_compute(data, tester, factor_family, all_factors)

            tester.sync_signal_index = None
            tester.sync_signal_index_replaced = None
            _token = _active_tester.set(tester)

            param_items = list(ic_param_map.items())

            compute = _compute_ic_groups(
                tester, param_items, param_payloads, primary_ic_lag,
                emitter=emitter,
            )
            response = _build_ic_response(
                tester, factors, all_products, compute,
                paths_hash, ic_lags, primary_ic_lag, ic_decay_lags, rolling_window,
            )
            emitter.emit_result(response)
        except Exception as e:
            emitter.emit_error(str(e), traceback=traceback.format_exc())
        finally:
            if _token is not None:
                _active_tester.reset(_token)
            emitter.close()

    threading.Thread(target=_compute_and_emit, daemon=True).start()
    return emitter.get_response()
