"""
Group test endpoint: /run_group_test /run_multi_horizon_group_test
"""
import logging, math, traceback
from typing import Any, cast
import numpy as np
import pandas as pd
from flask import request, jsonify
from tools.factors.FactorTester import _active_tester, _signal_time
from tools.factors.FactorRunResult import FactorRunResult
from tools.data.DataFreq import DataFreq
from tools.factors.tests.single_factor_test.group.core import infer_periods_per_year
from tools.factors.tests.single_factor_test.group.detail import build_group_detail
from tools.factors.tests.single_factor_test.group.monotonicity import build_group_ranking_detail
from . import sft_bp
import server.services.runtime_state as runtime_state
from server.modules.shared.price_data_helpers import to_utc_epoch

_log = logging.getLogger(__name__)


def _safe_float(v):
    """安全转为 float，NaN/inf 返回 None。"""
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(fv) or math.isinf(fv)) else fv


def _safe_bool(obj) -> bool:
    """安全求布尔值，避免 numpy 数组的 ambiguous truth value 错误。"""
    if obj is None:
        return False
    if isinstance(obj, np.ndarray):
        return bool(obj.size > 0)
    return bool(obj)


def _compute_return_metrics(r_array: np.ndarray, index_like=None, avg_turnover=None) -> dict:
    """从收益率序列计算绩效指标。"""
    s = pd.Series(r_array).replace([np.inf, -np.inf], np.nan).dropna()
    n = len(s)
    if n == 0:
        return {}
    annual_periods = infer_periods_per_year(index_like) if index_like is not None else 252.0
    cum_s = (1 + s).cumprod()
    dd = (cum_s.cummax() - cum_s) / cum_s.cummax()
    ls_annual = _safe_float((cum_s.iloc[-1] ** (annual_periods / n) - 1) * 100) if n > 1 else None
    ls_dd = _safe_float(dd.max() * 100) if n > 0 else None
    return {
        'Total Return':  _safe_float((cum_s.iloc[-1] - 1) * 100) if n > 0 else None,
        'Annual Return': ls_annual,
        'Volatility':    _safe_float(s.std() * (annual_periods ** 0.5) * 100),
        'Sharpe Ratio':  _safe_float((s.mean() * annual_periods) / (s.std() * annual_periods**0.5)) if s.std() != 0 else None,
        'Max Drawdown':  ls_dd,
        'Calmar Ratio':  _safe_float(float(ls_annual) / float(ls_dd)) if (ls_annual and ls_dd) else None,
        'Win Rate':      _safe_float((s > 0).sum() / n * 100) if n > 0 else None,
        'Mean Return':   _safe_float(s.mean() * 100),
        'Skewness':      _safe_float(s.skew()),
        'Kurtosis':      _safe_float(s.kurtosis()),
        'Avg Turnover':  _safe_float(avg_turnover),
    }


def _compute_ls_metrics(r_ls_array: np.ndarray, report_df: pd.DataFrame, index_like=None) -> dict:
    """从 Long-Short 收益率序列计算绩效指标。"""
    avg_turnover = round(float(
        (report_df['Avg Turnover'].iloc[0] + report_df['Avg Turnover'].iloc[-1]) / 2
    ), 4) if not report_df.empty and 'Avg Turnover' in report_df.columns else None
    return _compute_return_metrics(r_ls_array, index_like=index_like, avg_turnover=avg_turnover)


def _serialize_float_series(values: np.ndarray | list, default: float = 0.0) -> list:
    result = []
    for value in values:
        try:
            fv = float(value)
        except (TypeError, ValueError):
            result.append(default)
            continue
        result.append(round(fv, 8) if not (math.isnan(fv) or math.isinf(fv)) else default)
    return result


def _returns_to_cumulative(returns: np.ndarray) -> np.ndarray:
    safe = np.nan_to_num(np.asarray(returns, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    return np.cumprod(1.0 + safe)


def _normalize_weighted_legs(raw_legs, default_group: int) -> list[dict]:
    if not isinstance(raw_legs, list) or not raw_legs:
        raw_legs = [{'group': default_group, 'weight': 0.5}]
    legs = []
    for item in raw_legs:
        try:
            group = int(item.get('group') or 0)
            weight = float(item.get('weight') or 0)
        except (AttributeError, TypeError, ValueError):
            continue
        if weight > 0:
            legs.append({'group': group, 'weight': weight})
    total = sum(x['weight'] for x in legs)
    if total > 0:
        for leg in legs:
            leg['weight'] = leg['weight'] / total * 0.5
    return legs


def _parse_ls_config(data: dict, n_groups: int) -> dict:
    raw = data.get('ls_config') or {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        'name': str(raw.get('name') or 'Long-Short').strip() or 'Long-Short',
        'long': _normalize_weighted_legs(raw.get('long'), 0),
        'short': _normalize_weighted_legs(raw.get('short'), n_groups - 1),
    }


def _parse_ls_configs(data: dict, n_groups: int) -> list[dict]:
    """解析 LS configs 数组。只解析前端明确传入的 ls_configs，不传则返回空列表。"""
    raw_configs = data.get('ls_configs')
    if isinstance(raw_configs, list) and raw_configs:
        configs = []
        for raw in raw_configs:
            if not isinstance(raw, dict):
                continue
            parsed = _parse_ls_config({'ls_config': raw}, n_groups)
            if parsed['long'] and parsed['short']:
                configs.append(parsed)
        return configs
    return []


def _unique_group_key(name: str, used: set[str]) -> str:
    """去重：如果 name 已存在，追加 #2, #3..."""
    key = name or 'LS'
    suffix = 2
    while key in used:
        key = f'{name} #{suffix}'
        suffix += 1
    used.add(key)
    return key


def _normalize_group_names(group_names) -> dict[int, str]:
    if not isinstance(group_names, dict):
        return {}
    normalized: dict[int, str] = {}
    for key, value in group_names.items():
        try:
            normalized[int(key)] = str(value)
        except (TypeError, ValueError):
            continue
    return normalized


def _parse_group_variants(group_names) -> tuple[dict[int, str], dict[int, list[dict]] | None]:
    """Parse group_names for variant support.

    Accepts:
        {0: "A1", 1: "A2"}               → regular names, no variants
        {0: ["A1", "A1a"], 1: "A2"}     → group 0 has 2 variants (same group, different fees)

    Returns:
        (n_groups_name: dict[int, str], group_variants: dict[int, list[dict]] | None)
        - n_groups_name: one-to-one mapping (group_index → display_name).
          For variants, uses the first name as the group-level name.
        - group_variants: None if no variants detected.
          Otherwise, {group_index: [{name, fee_map}, ...]} where each variant has its own
          fee_map (populated later by _run_single_batch).
    """
    if not isinstance(group_names, dict):
        return {}, None
    n_groups_name: dict[int, str] = {}
    group_variants: dict[int, list[dict]] = {}
    has_variants = False
    for key, value in group_names.items():
        try:
            g = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(value, list):
            has_variants = True
            # Each element is either a str (name only) or a dict {name, fee_map}
            var_list: list[dict] = []
            for vi, item in enumerate(value):
                if isinstance(item, str):
                    var_list.append({'name': str(item), 'fee_map': None})
                elif isinstance(item, dict):
                    var_list.append({
                        'name': str(item.get('name', f'group_{g}_var_{vi}')),
                        'fee_map': item.get('fee_map') or None,
                        'fee_mode': item.get('fee_mode') or item.get('feeMode') or None,
                        'fee_rate': item.get('fee_rate', item.get('feeRate')),
                        'use_close_today': item.get('use_close_today', item.get('useCloseToday')),
                        'rebalance_mode': item.get('rebalance_mode') or item.get('rebalanceMode') or None,
                    })
            group_variants[g] = var_list
            # Use first variant's name as group-level display name
            n_groups_name[g] = var_list[0]['name'] if var_list else f'group_{g}'
        else:
            n_groups_name[g] = str(value)
    if has_variants:
        return n_groups_name, group_variants
    return n_groups_name, None


def _group_display_key(group_idx: int, n_base: int, derived_info: list[dict], group_names=None) -> str:
    names = _normalize_group_names(group_names)
    if group_idx in names:
        return names[group_idx]
    if group_idx >= n_base:
        di = derived_info[group_idx - n_base] if group_idx - n_base < len(derived_info) else {}
        return str(di.get('key') or di.get('name') or f'Group {group_idx + 1}')
    return str(group_idx)


def _metric_display_key(raw_key, n_base: int, derived_info: list[dict], group_names=None) -> str:
    try:
        key_int = int(raw_key)
    except (TypeError, ValueError):
        return str(raw_key)
    return _group_display_key(key_int, n_base, derived_info, group_names)


def _compute_weighted_ls_returns(gross_np: np.ndarray, fee_np: np.ndarray, ls_config: dict, n_groups: int) -> tuple[np.ndarray, np.ndarray]:
    gross_np = np.asarray(gross_np, dtype=float)
    fee_np = np.asarray(fee_np, dtype=float)
    legs = []
    for leg in ls_config.get('long') or []:
        if 0 <= leg['group'] < n_groups:
            legs.append({'side': 1.0, 'group': leg['group'], 'cap': leg['weight']})
    for leg in ls_config.get('short') or []:
        if 0 <= leg['group'] < n_groups:
            legs.append({'side': -1.0, 'group': leg['group'], 'cap': leg['weight']})
    if not legs:
        legs = [{'side': 1.0, 'group': 0, 'cap': 0.5}, {'side': -1.0, 'group': n_groups - 1, 'cap': 0.5}]

    total_cap = sum(leg['cap'] for leg in legs) or 1.0
    r_ls_list = []
    ls_cum_list = []
    for row_idx in range(gross_np.shape[0]):
        for leg in legs:
            group = leg['group']
            gross = leg['side'] * gross_np[row_idx, group]
            fee = fee_np[row_idx, group]
            net = (1.0 - fee) * (1.0 + gross) - 1.0
            net = 0.0 if (np.isnan(net) or np.isinf(net)) else float(net)
            leg['cap'] *= 1.0 + net
        new_total = sum(leg['cap'] for leg in legs)
        r_ls_list.append(new_total / total_cap - 1.0)
        ls_cum_list.append(new_total)
        total_cap = new_total
    return np.array(r_ls_list, dtype=float), np.array(ls_cum_list, dtype=float)


def _build_fee_vectors(group_result, fee_map, fee_uniform):
    """从 group_result.valid_cols 构建 (open_fv, close_fv, close_today_fv) 向量."""
    valid_cols = getattr(group_result, 'valid_cols', None)
    if valid_cols is None:
        return None, None, None

    def _variety(col) -> str:
        nm = getattr(col, "name", str(col))
        return nm.split(".")[0].upper()

    _fm = fee_map or {}
    half_fee = float(fee_uniform) / 2.0
    open_fv = np.array([
        float((_fm.get(_variety(c), {}) or {}).get("open", half_fee))
        for c in valid_cols
    ], dtype=float)
    close_fv = np.array([
        float((_fm.get(_variety(c), {}) or {}).get("close", half_fee))
        for c in valid_cols
    ], dtype=float)
    close_today_fv = np.array([
        float((_fm.get(_variety(c), {}) or {}).get("close_today", close_fv[i]))
        for i, c in enumerate(valid_cols)
    ], dtype=float)
    return open_fv, close_fv, close_today_fv


def _build_derived_group_payload(group_result, group_index: int, product_names: list[str], name: str,
                                  use_closetoday: bool = False,
                                  fee_map: dict | None = None,
                                  fee_uniform: float = 0.0,
                                  open_fv: np.ndarray | None = None,
                                  close_fv: np.ndarray | None = None,
                                  close_today_fv: np.ndarray | None = None,
                                  fee_override: dict | None = None) -> tuple[dict, dict]:
    from tools.products.product_utils import product_display_name
    from tools.factors.tests.single_factor_test.group.core import simulate_derived_group

    valid_cols = getattr(group_result, 'valid_cols', None)
    idx_list = getattr(group_result, 'index_list', None) or []
    if valid_cols is None:
        raise ValueError('当前分组结果缺少逐品种贡献，无法生成派生组')

    display_names = [product_display_name(product)['name'] for product in valid_cols]
    selected = {str(name) for name in (product_names or [])}
    selected_idx = [idx for idx, display_name in enumerate(display_names) if display_name in selected]
    if not selected_idx:
        raise ValueError('请至少选择一个有效品种')

    if open_fv is None:
        _open_fv, _close_fv, _close_today_fv = _build_fee_vectors(group_result, fee_map, fee_uniform)
        if _open_fv is None or _close_fv is None or _close_today_fv is None:
            raise ValueError('当前分组结果缺少逐品种贡献，无法生成派生组')
        open_fv, close_fv, close_today_fv = _open_fv, _close_fv, _close_today_fv

    # Apply fee_override: uniform override per fee type for this derived group
    fo = fee_override or {}
    if fo.get('open') is not None:
        open_fv = np.full_like(open_fv, float(fo['open']))
    if fo.get('close') is not None:
        close_fv = np.full_like(close_fv, float(fo['close']))
    if fo.get('close_today') is not None:
        close_today_fv = np.full_like(close_today_fv, float(fo['close_today']))

    assert close_fv is not None and close_today_fv is not None
    sim = simulate_derived_group(
        group_index=group_index,
        selected_idx=selected_idx,
        group_result=group_result,
        open_fee_vec=open_fv,
        close_fee_vec=close_fv,
        close_today_fee_vec=close_today_fv,
        rebalance_mode=getattr(group_result, 'rebalance_mode', 'buy_and_hold'),
        use_closetoday=use_closetoday,
    )

    timestamps = [to_utc_epoch(_signal_time(d)) for d in idx_list]
    metric = _compute_return_metrics(sim['net_returns'], index_like=idx_list, avg_turnover=None)

    group = {
        'name': name or f'第{group_index + 1}组精选',
        'timestamps': timestamps,
        'cumulative_returns': _serialize_float_series(sim['cumulative'], default=0.0),
        'gross_returns': _serialize_float_series(sim['gross_returns'], default=0.0),
        'fee_costs': _serialize_float_series(sim['fee_costs'], default=0.0),
        'trade_notional_ratios': _serialize_float_series(sim['notional_ratios'], default=0.0),
        'is_derived': True,
        'derived': {
            'base_group': group_index,
            'product_names': [display_names[idx] for idx in selected_idx],
        },
    }
    return group, metric


def _build_derived_groups_batch_payload(group_result, entries: list[dict],
                                         use_closetoday: bool = False,
                                         fee_map: dict | None = None,
                                         fee_uniform: float = 0.0) -> list[dict]:
    """一次 simulate_derived_groups_batch 调用，返回 [{success, group?, metric?, error?}, ...]。

    同一 group_index 的条目合并为一次 simulate_groups 调用。
    不同 group_index 的条目各自发送独立请求（此时回退到逐个 simulate_derived_group）。
    """
    from tools.products.product_utils import product_display_name
    from tools.factors.tests.single_factor_test.group.core import simulate_derived_group, simulate_derived_groups_batch

    valid_cols = getattr(group_result, 'valid_cols', None)
    idx_list = getattr(group_result, 'index_list', None) or []
    if valid_cols is None:
        raise ValueError('当前分组结果缺少逐品种贡献，无法生成派生组')

    display_names = [product_display_name(product)['name'] for product in valid_cols]
    _ofv, _cfv, _ctfv = _build_fee_vectors(group_result, fee_map, fee_uniform)
    if _ofv is None or _cfv is None or _ctfv is None:
        raise ValueError('当前分组结果缺少逐品种贡献，无法生成派生组')
    open_fv: np.ndarray = _ofv
    close_fv: np.ndarray = _cfv
    close_today_fv: np.ndarray = _ctfv

    # 按 group_index 分组
    groups_by_gi: dict = {}
    for i, entry in enumerate(entries):
        gi = entry.get('group_index')
        pn = entry.get('product_names') or []
        nm = str(entry.get('name') or '').strip()
        feo = entry.get('fee_override')
        if gi is None:
            continue
        if not nm:
            nm = f'第{int(gi) + 1}组精选'
        selected_idx = [idx for idx, dn in enumerate(display_names) if dn in {str(n) for n in pn}]
        if not selected_idx:
            continue
        groups_by_gi.setdefault(int(gi), []).append({
            'orig_index': i,
            'group_index': int(gi),
            'name': nm,
            'selected_idx': selected_idx,
            'fee_override': feo if isinstance(feo, dict) else None,
        })

    # 结果数组，按原始顺序填充
    results: list = [None] * len(entries)

    rebalance_mode = getattr(group_result, 'rebalance_mode', 'buy_and_hold')
    timestamps = [to_utc_epoch(_signal_time(d)) for d in idx_list]

    for gi, items in groups_by_gi.items():
        if len(items) == 1:
            # 只有 1 个派生组 → 回退到逐个 API
            item = items[0]
            # Apply per-entry fee_override
            item_open_fv = open_fv.copy()
            item_close_fv = close_fv.copy()
            item_ct_fv = close_today_fv.copy()
            feo = item.get('fee_override')
            if feo:
                if feo.get('open') is not None:
                    item_open_fv[:] = float(feo['open'])
                if feo.get('close') is not None:
                    item_close_fv[:] = float(feo['close'])
                if feo.get('close_today') is not None:
                    item_ct_fv[:] = float(feo['close_today'])
            try:
                sim = simulate_derived_group(
                    group_index=gi,
                    selected_idx=item['selected_idx'],
                    group_result=group_result,
                    open_fee_vec=item_open_fv,
                    close_fee_vec=item_close_fv,
                    close_today_fee_vec=item_ct_fv,
                    rebalance_mode=rebalance_mode,
                    use_closetoday=use_closetoday,
                )
                metric = _compute_return_metrics(sim['net_returns'], index_like=idx_list, avg_turnover=None)
                results[item['orig_index']] = {
                    'index': item['orig_index'],
                    'success': True,
                    'group': {
                        'name': item['name'],
                        'timestamps': timestamps,
                        'cumulative_returns': _serialize_float_series(sim['cumulative'], default=0.0),
                        'gross_returns': _serialize_float_series(sim['gross_returns'], default=0.0),
                        'fee_costs': _serialize_float_series(sim['fee_costs'], default=0.0),
                        'trade_notional_ratios': _serialize_float_series(sim['notional_ratios'], default=0.0),
                        'is_derived': True,
                        'derived': {
                            'base_group': gi,
                            'product_names': [display_names[idx] for idx in item['selected_idx']],
                        },
                    },
                    'metric': metric,
                }
            except Exception as e:
                results[item['orig_index']] = {'index': item['orig_index'], 'success': False, 'error': str(e)}
        else:
            # 多个派生组共享同一基础组 → 批量一次 simulate_groups
            # Apply each entry's fee_override
            derivations = []
            for item in items:
                dd = {'selected_idx': item['selected_idx'], 'name': item['name']}
                feo = item.get('fee_override')
                if feo:
                    dd['fee_override'] = feo
                derivations.append(dd)
            sims = simulate_derived_groups_batch(
                group_index=gi,
                derivations=derivations,
                group_result=group_result,
                open_fee_vec=open_fv,
                close_fee_vec=close_fv,
                close_today_fee_vec=close_today_fv,
                rebalance_mode=rebalance_mode,
                use_closetoday=use_closetoday,
            )
            for j, item in enumerate(items):
                sim = sims[j]
                metric = _compute_return_metrics(sim['net_returns'], index_like=idx_list, avg_turnover=None)
                results[item['orig_index']] = {
                    'index': item['orig_index'],
                    'success': True,
                    'group': {
                        'name': item['name'],
                        'timestamps': timestamps,
                        'cumulative_returns': _serialize_float_series(sim['cumulative'], default=0.0),
                        'gross_returns': _serialize_float_series(sim['gross_returns'], default=0.0),
                        'fee_costs': _serialize_float_series(sim['fee_costs'], default=0.0),
                        'trade_notional_ratios': _serialize_float_series(sim['notional_ratios'], default=0.0),
                        'is_derived': True,
                        'derived': {
                            'base_group': gi,
                            'product_names': [display_names[idx] for idx in item['selected_idx']],
                        },
                    },
                    'metric': metric,
                }

    return results


def _latest_group_result(tester):
    factor = getattr(tester, 'last_group_factor', None)
    if factor is None:
        return None
    result = tester.results.get(factor) if hasattr(tester, 'results') else None
    return result.group_result if result is not None else None


def _parse_group_fee_config(data, products: set | None = None):
    """解析前端费率配置。

    前端三种模式：
    1. 不扣除费用 → fee=0, fee_map={}
    2. 统一费率   → fee>0, fee_map={}
    3. 按品种费率 → fee=0, fee_map 非空（来自前端 /get_fee_table 的 FeeData 全量，
                   含用户 _feeModifications 覆盖 + 平今/平昨选择）

    返回 (fee_uniform, fee_map, use_closetoday)，
    其中 fee_map 仅在模式3时非空，key 格式：{open, close, close_today, close_yesterday}，
    值为单边费率（按金额比例）。
    模式1/2 时 fee_map 为空字典，由调用方用 fee_uniform 的 half_fee 作为 fallback。
    """
    fee_uniform = float(data.get('fee', 0.0) or 0.0) / 100.0
    fee_map_raw = data.get('fee_map', {}) or {}
    use_closetoday = bool(data.get('use_closetoday', False))

    # 模式1/2：不扣除或统一费率 → fee_map 保持空
    if not fee_map_raw:
        return fee_uniform, {}, use_closetoday

    # 模式3：按品种费率 → 前端已传全量 FeeData + 用户覆盖，
    # 只需做字段名映射：open_ratio→open, close_ratio→close, closetoday_ratio→close_today/close_yesterday
    fee_map: dict[str, dict[str, float]] = {}
    for code, rates in fee_map_raw.items():
        code_upper = str(code).upper()
        o = float(rates.get('open_ratio', 0) or 0)
        c = float(rates.get('close_ratio', 0) or 0)
        ct = float(rates.get('closetoday_ratio', 0) or 0)
        fee_map[code_upper] = {
            'open': o,
            'close': c,
            'close_today': ct,
            'close_yesterday': c,  # 平昨=平仓费率
        }

    return fee_uniform, fee_map, use_closetoday


def _product_fee_rates_by_name(group_result) -> dict[str, dict[str, float]]:
    """返回 {产品名: {open, close, close_today, close_yesterday, total}} 的费率字典。

    费率向量已在回测阶段按前端选择的模式（不扣除/统一/按品种）设置，
    此处直接使用，按产品名索引。
    """
    valid_cols = getattr(group_result, 'valid_cols', None)
    open_fee_vec = getattr(group_result, 'open_fee_vec', None)
    close_fee_vec = getattr(group_result, 'close_fee_vec', None)
    close_today_fee_vec = getattr(group_result, 'close_today_fee_vec', None)
    _cy_vec = getattr(group_result, 'close_yesterday_fee_vec', None)
    close_yesterday_fee_vec = _cy_vec if _cy_vec is not None else close_fee_vec
    if not _safe_bool(valid_cols) or open_fee_vec is None or close_fee_vec is None:
        return {}
    from tools.products.product_utils import product_display_name

    open_rates = np.asarray(open_fee_vec, dtype=float)
    close_rates = np.asarray(close_fee_vec, dtype=float)
    close_today_rates = (
        np.asarray(close_today_fee_vec, dtype=float)
        if close_today_fee_vec is not None else close_rates
    )
    close_yesterday_rates = np.asarray(close_yesterday_fee_vec, dtype=float)
    cols = valid_cols or []
    if len(cols) != open_rates.shape[0] or len(cols) != close_rates.shape[0]:
        return {}

    rates = {}
    for idx, product in enumerate(cols):
        name = product_display_name(product)['name']
        rates[name] = {
            'open': float(open_rates[idx]),
            'close': float(close_rates[idx]),
            'close_today': float(close_today_rates[idx]),
            'close_yesterday': float(close_yesterday_rates[idx]),
            'total': float(open_rates[idx]) + float(close_rates[idx]),
        }
    return rates


def _display_product_with_fee(product, fee_rates_by_name: dict[str, dict[str, float]]) -> dict[str, Any]:
    from tools.products.product_utils import product_display_name

    display: dict[str, Any] = product_display_name(product)
    display['fee'] = fee_rates_by_name.get(display['name'])
    return display


def _run_single_batch(*, submission_id, factor_alias, n_groups,
                      fee_uniform, fee_map, use_closetoday,
                      rebalance_mode, start_date, end_date,
                      return_freqs=None, derived_groups=None,
                      ls_configs=None, group_names=None,
                      group_fee_maps=None) -> dict:
    """执行单个 batch 的分组测试，返回结果 dict（不含 Flask Response 包装）。
    
    此函数设计为线程安全：每个调用独立获取 tester、快照 products、计算后恢复。
    
    group_names: 可选 dict[int,str]，key 为 0-based 组索引，value 为显示名（如 {0:"B1", 3:"B4"}）。
    若提供，groups_data 中每个组将带 key 字段，metrics 的 key 也用它。
    若不提供，退化为 "Group N" (base) / derived name。
    """
    _gt_token = None
    _saved_products = None
    tester = None
    try:
        tester = runtime_state.get_factor_tester(submission_id, caller='run_single_batch')
        # 快照 products 以防并发修改
        _saved_products = tester.products.copy()
        tester.products = set(_saved_products)

        # ── 解析 group_names 中的 variant（一对多费率）──
        n_groups_name_parsed, group_variants = _parse_group_variants(group_names)
        if n_groups_name_parsed:
            n_groups_name = n_groups_name_parsed
        else:
            n_groups_name = {i: f"Group {i+1}" for i in range(n_groups)}

        factor = next((f for f in tester.factors if f.alias == factor_alias or f.name == factor_alias), None)
        if not factor:
            if not getattr(tester, 'factors', None):
                return {
                    'success': False,
                    'error': '当前测试器尚未生成因子实例。请先在 IC 测试模块运行一次 IC 测试。',
                    'needs_ic_test': True,
                }
            return {'success': False, 'error': f'未找到因子 {factor_alias}'}

        time_range = None
        if start_date and end_date:
            start_dt = pd.to_datetime(start_date)
            end_dt = pd.to_datetime(end_date)
            tz = getattr(tester.start_date, 'tz', None) if hasattr(tester.start_date, 'tz') else None
            if tz:
                if start_dt.tzinfo is None:
                    start_dt = start_dt.tz_localize(tz)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.tz_localize(tz)
            time_range = (start_dt, end_dt)

        _gt_token = _active_tester.set(tester)

        # ── 多周期对比 ──
        if return_freqs and isinstance(return_freqs, list) and len(return_freqs) > 0:
            _saved = factor in tester.results
            _saved_freq = tester.results.get(factor, FactorRunResult()).return_freq
            _saved_returns = tester.results.get(factor, FactorRunResult()).returns.copy() if _saved else pd.DataFrame()

            multi_horizon_results = []
            for rf_str in return_freqs:
                try:
                    freq = DataFreq(rf_str) if rf_str else None
                except Exception:
                    freq = None
                r = tester._get_result(factor)
                r.return_freq = freq if freq is not None else None
                r.returns = pd.DataFrame()
                _, _returns_dict, report_df, cum_np, idx_list = tester.test_by_group(
                    factors=factor, n_groups=n_groups, time_range=time_range,
                    plot_flag=False, save_plot=False, plot_show=False,
                    fee=fee_uniform, fee_map=fee_map,
                    use_closetoday=use_closetoday,
                    rebalance_mode=rebalance_mode,
                    derived_groups=derived_groups,
                    group_fee_maps=group_fee_maps,
                    n_groups_name=n_groups_name,
                    group_variants=group_variants,
                )
                timestamps = [to_utc_epoch(_signal_time(d)) for d in idx_list]
                group_result = tester._get_result(factor).group_result
                _gross = group_result.gross_returns_np if group_result is not None else None
                gross_np = _gross if _gross is not None else np.zeros((len(timestamps), n_groups))
                _fee_np = group_result.fee_costs_np if group_result is not None else None
                fee_np_arr = _fee_np if _fee_np is not None else np.zeros((len(timestamps), n_groups))

                r_ls_np, _ = _compute_weighted_ls_returns(gross_np, fee_np_arr, ls_configs[0], n_groups) if ls_configs else (np.array([]), np.array([]))
                ls_metric = _compute_ls_metrics(r_ls_np, report_df, idx_list) if ls_configs else {}
                freq_label = str(rf_str) if rf_str else factor.freq.name if factor.freq else 'base'
                multi_horizon_results.append({
                    'return_freq': freq_label,
                    'ls_metrics': ls_metric,
                    'report': report_df.to_dict(orient='index') if not report_df.empty else {},
                })

            if factor in tester.results:
                tester.results[factor].return_freq = _saved_freq
                tester.results[factor].returns = _saved_returns

            _gr = tester._get_result(factor).group_result
            return {
                'success': True, 'multi_horizon': True,
                'results': multi_horizon_results, 'n_groups': n_groups,
                'multi_session_active': bool(_gr.multi_session_active) if _gr is not None else False,
                'rebalance_mode': rebalance_mode,
                'submission_id': submission_id, 'factor_alias': factor_alias,
                'tester_alias': getattr(tester, 'alias', '?'),
                'tester_product_count': len(tester.products) if hasattr(tester, 'products') else 0,
            }

        # ── 单频率 ──
        _, _returns_dict, report_df, cum_np, idx_list = tester.test_by_group(
            factors=factor, n_groups=n_groups, time_range=time_range,
            plot_flag=False, save_plot=False, plot_show=False,
            fee=fee_uniform, fee_map=fee_map,
            use_closetoday=use_closetoday,
            rebalance_mode=rebalance_mode,
            derived_groups=derived_groups,
            group_fee_maps=group_fee_maps,
            n_groups_name=n_groups_name,
            group_variants=group_variants,
        )

        timestamps = [to_utc_epoch(_signal_time(d)) for d in idx_list]
        group_result = tester._get_result(factor).group_result
        n_total = group_result.returns_np.shape[1] if group_result is not None else n_groups
        n_base = getattr(group_result, 'n_base', n_groups) or n_groups
        n_derived = getattr(group_result, 'n_derived', 0) or 0
        derived_info = getattr(group_result, 'derived_info', None) or []
        _gross = group_result.gross_returns_np if group_result is not None else None
        gross_np = _gross if _gross is not None else np.zeros((len(timestamps), n_total))
        _fee = group_result.fee_costs_np if group_result is not None else None
        fee_np = _fee if _fee is not None else np.zeros((len(timestamps), n_total))

        result_group_names = getattr(group_result, 'group_names', None) or _normalize_group_names(group_names)
        groups_data = []
        for g in range(n_total):
            is_derived = g >= n_base
            vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else None for v in cum_np[:, g]]
            gross_vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else 0.0 for v in gross_np[:, g]]
            fee_vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else 0.0 for v in fee_np[:, g]]
            group_key = _group_display_key(g, n_base, derived_info, result_group_names)
            if is_derived:
                di = derived_info[g - n_base]
                group_name = di.get('name', f'Group {g + 1}')
            else:
                group_name = group_key
            entry = {
                'key': group_key,
                'name': group_name,
                'group_index': g,
                'timestamps': timestamps,
                'cumulative_returns': vals,
                'gross_returns': gross_vals,
                'fee_costs': fee_vals,
                'trade_notional_ratios': [
                    round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else 0.0
                    for v in group_result.trade_notional_ratio_np[:, g]
                ] if group_result is not None and group_result.trade_notional_ratio_np is not None else [],
            }
            if is_derived:
                di = derived_info[g - n_base]
                entry['is_derived'] = True
                entry['derived'] = {
                    'base_group': di['base_group'],
                    'product_names': di['product_names'],
                    'id': di.get('id'),
                }
            groups_data.append(entry)

        metrics: dict = {}
        if not report_df.empty:
            raw_metrics = report_df.to_dict(orient='index')
            for k, v in raw_metrics.items():
                display_key = _metric_display_key(k, n_base, derived_info, result_group_names)
                metrics[display_key] = {
                    mk: (None if mv is None or (isinstance(mv, float) and (math.isnan(mv) or math.isinf(mv))) else float(mv))
                    for mk, mv in v.items()
                }
        used_keys = set(metrics.keys())
        if ls_configs:
            for ls_config in ls_configs:
                r_ls, ls_cum_arr = _compute_weighted_ls_returns(gross_np, fee_np, ls_config, n_total)
                # LS key: 去重后的唯一标识，name: 原始描述
                ls_name = ls_config['name'] or 'Long-Short'
                ls_key = _unique_group_key(ls_name, used_keys)
                ls_vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else None for v in ls_cum_arr]
                groups_data.append({
                    'key': ls_key,
                    'name': ls_name,
                    'timestamps': timestamps,
                    'cumulative_returns': ls_vals,
                    'gross_returns': _serialize_float_series(r_ls, default=0.0),
                    'fee_costs': [0.0] * len(r_ls),
                    'trade_notional_ratios': [0.0] * len(r_ls),
                    'is_ls': True,
                    'is_derived': True,
                    'derived': {'type': 'long_short', 'key': ls_key, 'config': ls_config},
                })
                metrics[ls_key] = _compute_ls_metrics(r_ls, report_df, idx_list)

        return {
            'success': True,
            'groups': groups_data, 'metrics': metrics,
            'n_groups': n_total, 'n_base': n_base,
            'multi_session_active': bool(group_result.multi_session_active) if group_result is not None else False,
            'rebalance_mode': rebalance_mode,
            'submission_id': submission_id, 'factor_alias': factor_alias,
            'tester_alias': getattr(tester, 'alias', '?'),
            'tester_product_count': len(tester.products) if hasattr(tester, 'products') else 0,
            # 原始数据：供跨 batch LS 计算使用（不进入最终 JSON）
            '_raw': {
                'gross_np': gross_np,
                'fee_np': fee_np,
                'timestamps': timestamps,
                'report_df': report_df,
                'idx_list': idx_list,
            },
        }
    except Exception as e:
        return {'success': False, 'error': str(e), 'traceback': traceback.format_exc()}
    finally:
        if _saved_products is not None and tester is not None:
            tester.products = _saved_products
        if _gt_token is not None:
            _active_tester.reset(_gt_token)


@sft_bp.route('/run_group_test_batch', methods=['POST'])
def run_group_test_batch():
    """批量并行运行多个 batch 的分组测试，支持跨 batch Long-Short。
    
    Request JSON:
    {
        "batches": [
            {"submission_id": "...", "factor_alias": "...", "n_groups": 5, "ls_configs": [...]},
            ...
        ],
        "cross_batch_ls": [
            {"name": "LS-A", "long": {"submission_id": "...", "factor_alias": "...", "group": 0},
                          "short": {"submission_id": "...", "factor_alias": "...", "group": 4}},
            ...
        ],
        "fee": 0.0001, "fee_map": {...}, "use_closetoday": false,
        "start_date": "2024-01-01", "end_date": "2024-12-31",
        "return_freqs": null, "rebalance_mode": "buy_and_hold",
        "derived_groups": null
    }
    
    cross_batch_ls 中 group 为 0-based 组索引。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    data = request.get_json()
    batches_raw = data.get('batches')
    if not isinstance(batches_raw, list) or not batches_raw:
        return jsonify({'success': False, 'error': 'batches 必须是非空数组'}), 400

    cross_batch_ls_raw = data.get('cross_batch_ls') or []

    rebalance_mode = str(data.get('rebalance_mode', 'buy_and_hold') or 'buy_and_hold')
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    return_freqs = data.get('return_freqs', None)
    derived_groups = data.get('derived_groups', None)
    group_fee_maps = data.get('group_fee_maps', None)
    # group_fee_maps: {group_index: {variety_code: {open, close, close_today, ...}}} 或 null
    if group_fee_maps is not None and isinstance(group_fee_maps, dict):
        group_fee_maps = {int(k): v for k, v in group_fee_maps.items()}

    # 费率从第一个 batch 的 tester 解析
    first_batch = batches_raw[0]
    try:
        sub_id = first_batch.get('submission_id')
        tester0 = runtime_state.get_factor_tester(sub_id, caller='run_group_test_batch')
        fee_uniform, fee_map, use_closetoday = _parse_group_fee_config(data, getattr(tester0, 'products', None))
    except Exception as e:
        return jsonify({'success': False, 'error': f'费率解析失败: {e}'}), 400

    # 构建 batch→index 映射（用于跨 batch LS 查找）
    batch_index_by_key: dict[str, int] = {}  # "submission_id|factor_alias" → index
    for i, b in enumerate(batches_raw):
        key = f"{b.get('submission_id','')}|{b.get('factor_alias','')}"
        batch_index_by_key[key] = i

    def _run_one(batch: dict) -> dict:
        submission_id = batch.get('submission_id')
        factor_alias = batch.get('factor_alias')
        n_groups = batch.get('n_groups', 5)
        group_names = batch.get('group_names')
        batch_derived_groups = batch.get('derived_groups')
        if not isinstance(batch_derived_groups, list):
            batch_derived_groups = derived_groups
        raw_ls = batch.get('ls_configs')
        ls_configs = None
        if isinstance(raw_ls, list) and raw_ls:
            ls_configs = []
            for raw in raw_ls:
                if isinstance(raw, dict):
                    parsed = _parse_ls_config({'ls_config': raw}, int(n_groups))
                    if parsed['long'] and parsed['short']:
                        ls_configs.append(parsed)

        result = _run_single_batch(
            submission_id=submission_id,
            factor_alias=factor_alias,
            n_groups=n_groups,
            fee_uniform=fee_uniform,
            fee_map=fee_map,
            use_closetoday=use_closetoday,
            rebalance_mode=rebalance_mode,
            start_date=start_date,
            end_date=end_date,
            return_freqs=return_freqs,
            derived_groups=batch_derived_groups,
            ls_configs=ls_configs,
            group_names=group_names,
            group_fee_maps=group_fee_maps,
        )
        result['batch_submission_id'] = submission_id
        result['batch_factor_alias'] = factor_alias
        result['batch_n_groups'] = n_groups
        return result

    # ── 阶段 1：并行计算所有 batch ──
    batch_results: list[dict | None] = [None] * len(batches_raw)  # 按原始顺序
    errors = []
    max_workers = min(len(batches_raw), 6)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run_one, b): i for i, b in enumerate(batches_raw)}
        for future in as_completed(futures):
            idx = futures[future]
            try:
                r = future.result()
            except Exception as e:
                errors.append({'index': idx, 'error': str(e)})
                continue
            if r.get('success'):
                batch_results[idx] = r
            else:
                errors.append({'index': idx, 'submission_id': batches_raw[idx].get('submission_id'),
                               'factor_alias': batches_raw[idx].get('factor_alias'),
                               'error': r.get('error', '未知错误'),
                               'traceback': r.get('traceback')})

    # 过滤掉 None（失败的 batch）
    valid_results = [r for r in batch_results if r is not None]
    if not valid_results:
        first_err = errors[0] if errors else {'error': '所有 batch 均失败'}
        return jsonify({
            'success': False,
            'error': first_err.get('error', '所有 batch 均失败'),
            'traceback': first_err.get('traceback'),
            'batch_errors': errors,
        }), 500

    # ── 阶段 2：跨 batch LS 计算 ──
    def _find_raw(br_dict: dict | None) -> dict | None:
        return br_dict.get('_raw') if br_dict else None

    cross_ls_groups: list[dict] = []
    cross_ls_metrics: dict = {}

    if cross_batch_ls_raw and not return_freqs:
        # 只有单频率才支持跨 batch LS
        for cb in cross_batch_ls_raw:
            if not isinstance(cb, dict):
                continue
            long_info: dict = cb.get('long') or {}
            short_info: dict = cb.get('short') or {}
            ls_name = str(cb.get('name') or 'Long-Short').strip() or 'Long-Short'

            long_key = f"{long_info.get('submission_id','')}|{long_info.get('factor_alias','')}"
            short_key = f"{short_info.get('submission_id','')}|{short_info.get('factor_alias','')}"
            long_bi = batch_index_by_key.get(long_key)
            short_bi = batch_index_by_key.get(short_key)

            if long_bi is None or short_bi is None:
                continue

            long_br = batch_results[long_bi]
            short_br = batch_results[short_bi]
            if long_br is None or short_br is None:
                continue
            long_raw = _find_raw(long_br)
            short_raw = _find_raw(short_br)
            if long_raw is None or short_raw is None:
                continue

            long_group = int(long_info.get('group', 0))
            short_group = int(short_info.get('group', 0))
            long_n = long_br.get('batch_n_groups', 5)
            short_n = short_br.get('batch_n_groups', 5)

            # 跨 batch LS：从不同 batch 的 gross_np / fee_np 拼成 (T, 2) 数组
            gross_long = long_raw['gross_np'][:, long_group] if long_group < long_raw['gross_np'].shape[1] else np.zeros(long_raw['gross_np'].shape[0])
            fee_long = long_raw['fee_np'][:, long_group] if long_group < long_raw['fee_np'].shape[1] else np.zeros(long_raw['fee_np'].shape[0])
            gross_short = short_raw['gross_np'][:, short_group] if short_group < short_raw['gross_np'].shape[1] else np.zeros(short_raw['gross_np'].shape[0])
            fee_short = short_raw['fee_np'][:, short_group] if short_group < short_raw['fee_np'].shape[1] else np.zeros(short_raw['fee_np'].shape[0])

            # 对齐时间轴：取较短的
            min_len = min(len(gross_long), len(gross_short))
            gross_long = gross_long[:min_len]
            fee_long = fee_long[:min_len]
            gross_short = gross_short[:min_len]
            fee_short = fee_short[:min_len]

            # 拼成 (T, 2) 并调用 _compute_weighted_ls_returns
            gross_combined = np.column_stack([gross_long, gross_short])
            fee_combined = np.column_stack([fee_long, fee_short])

            ls_config = {
                'name': ls_name,
                'long': [{'group': 0, 'weight': 1.0}],
                'short': [{'group': 1, 'weight': 1.0}],
            }
            r_ls, ls_cum_arr = _compute_weighted_ls_returns(gross_combined, fee_combined, ls_config, 2)

            # 用第一个 batch 的 report_df 和 idx_list 来计算 metrics（近似）
            ref_raw = long_raw
            ref_report = ref_raw['report_df']
            ref_idx = ref_raw['idx_list']
            timestamps = ref_raw['timestamps'][:min_len]
            ls_vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else None for v in ls_cum_arr]

            ls_key = ls_name
            cross_ls_groups.append({
                'key': ls_key,
                'name': ls_name,
                'timestamps': timestamps,
                'cumulative_returns': ls_vals,
                'gross_returns': _serialize_float_series(r_ls, default=0.0),
                'fee_costs': [0.0] * len(r_ls),
                'trade_notional_ratios': [0.0] * len(r_ls),
                'is_ls': True,
                'is_derived': True,
                'is_cross_batch': True,
                'derived': {
                    'type': 'long_short',
                    'long_batch': long_info,
                    'short_batch': short_info,
                },
            })
            cross_ls_metrics[ls_key] = _compute_ls_metrics(r_ls, ref_report, ref_idx)

    # ── 阶段 3：合并结果 ──
    merged_groups = []
    merged_metrics = {}
    used_merged_keys: set[str] = set()
    last_n_groups = 0
    last_multi_session = False
    last_rebalance = rebalance_mode

    for br in valid_results:
        if br.get('multi_horizon'):
            return jsonify({
                'success': True, 'multi_horizon': True,
                'results': br.get('results', []),
                'n_groups': br.get('n_groups', 5),
                'multi_session_active': br.get('multi_session_active', False),
                'rebalance_mode': br.get('rebalance_mode', rebalance_mode),
                'submission_id': br.get('submission_id', ''),
                'factor_alias': br.get('factor_alias', ''),
                'tester_alias': br.get('tester_alias', '?'),
                'tester_product_count': br.get('tester_product_count', 0),
            })
        # 移除 _raw 内部数据（不进入 JSON）
        br.pop('_raw', None)
        br_metrics = br.get('metrics') or {}
        consumed_metric_keys: set[str] = set()
        if br.get('groups'):
            for group in br['groups']:
                original_key = str(group.get('key') or group.get('name') or f'Group {len(merged_groups) + 1}')
                merged_key = _unique_group_key(original_key, used_merged_keys)
                if merged_key != original_key:
                    group = dict(group)
                    group['key'] = merged_key
                    if isinstance(group.get('derived'), dict) and group['derived'].get('key') == original_key:
                        group['derived'] = dict(group['derived'])
                        group['derived']['key'] = merged_key
                merged_groups.append(group)
                if original_key in br_metrics:
                    merged_metrics[merged_key] = br_metrics[original_key]
                    consumed_metric_keys.add(original_key)
        for metric_key, metric_value in br_metrics.items():
            if metric_key in consumed_metric_keys:
                continue
            merged_key = _unique_group_key(str(metric_key), used_merged_keys)
            merged_metrics[merged_key] = metric_value
        last_n_groups = br.get('n_groups', last_n_groups)
        last_multi_session = br.get('multi_session_active', last_multi_session) or last_multi_session
        last_rebalance = br.get('rebalance_mode', last_rebalance) or last_rebalance

    # 追加跨 batch LS 组
    if cross_ls_groups:
        for group in cross_ls_groups:
            original_key = str(group.get('key') or group.get('name') or 'Long-Short')
            merged_key = _unique_group_key(original_key, used_merged_keys)
            if merged_key != original_key:
                group = dict(group)
                group['key'] = merged_key
                if isinstance(group.get('derived'), dict):
                    group['derived'] = dict(group['derived'])
                    group['derived']['key'] = merged_key
            merged_groups.append(group)
            if original_key in cross_ls_metrics:
                merged_metrics[merged_key] = cross_ls_metrics[original_key]

    return jsonify({
        'success': True,
        'groups': merged_groups,
        'metrics': merged_metrics,
        'n_groups': last_n_groups,
        'multi_session_active': last_multi_session,
        'rebalance_mode': last_rebalance,
        'submission_id': batches_raw[0].get('submission_id', ''),
        'factor_alias': batches_raw[0].get('factor_alias', ''),
        'tester_alias': valid_results[0].get('tester_alias', '?') if valid_results else '?',
        'tester_product_count': valid_results[0].get('tester_product_count', 0) if valid_results else 0,
        'batch_count': len(valid_results),
        'cross_batch_ls_count': len(cross_ls_groups),
        'errors': errors if errors else None,
    })


@sft_bp.route('/run_group_test', methods=['POST'])
def run_group_test():
    data = request.get_json()
    submission_id  = data.get('submission_id')
    factor_alias   = data.get('factor_alias')
    n_groups       = data.get('n_groups', 5)
    ls_configs = _parse_ls_configs(data, int(n_groups))
    rebalance_mode: str = str(data.get('rebalance_mode', 'buy_and_hold') or 'buy_and_hold')
    start_date = data.get('start_date')
    end_date   = data.get('end_date')
    # 多周期对比：传入 return_freqs 数组，如 ["1d","3d","5d","10d"]
    return_freqs: list = data.get('return_freqs', None)
    _gt_token = None
    _saved_products = None
    tester = None
    try:
        tester = runtime_state.get_factor_tester(submission_id, caller='run_group_test')
        fee_uniform, fee_map, use_closetoday = _parse_group_fee_config(data, getattr(tester, 'products', None))

        # 快照 products 以防并发请求（如 IC 测试或 delete_path）修改共享的 tester.products
        _saved_products = tester.products.copy()
        tester.products = set(_saved_products)

        factor = next((f for f in tester.factors if f.alias == factor_alias or f.name == factor_alias), None)
        if not factor:
            if not getattr(tester, 'factors', None):
                return jsonify({
                    'success': False,
                    'error': '当前测试器尚未生成因子实例。请先在 IC 测试模块运行一次 IC 测试，再运行分组测试。',
                    'needs_ic_test': True,
                }), 400
            return jsonify({'success': False, 'error': f'未找到因子 {factor_alias}，可用因子: {[(f.alias, f.name) for f in tester.factors]}'}), 404

        time_range = None
        if start_date and end_date:
            try:
                start_dt = pd.to_datetime(start_date)
                end_dt   = pd.to_datetime(end_date)
                tz = getattr(tester.start_date, 'tz', None) if hasattr(tester.start_date, 'tz') else None
                if tz:
                    if start_dt.tzinfo is None: start_dt = start_dt.tz_localize(tz)
                    if end_dt.tzinfo is None:   end_dt   = end_dt.tz_localize(tz)
                time_range = (start_dt, end_dt)
            except Exception as e:
                return jsonify({'success': False, 'error': f'时间范围格式错误: {e}'}), 400

        _gt_token = _active_tester.set(tester)

        # ─── 如果是多周期对比 ───
        if return_freqs and isinstance(return_freqs, list) and len(return_freqs) > 0:
            # Save original FactorRunResult state before multi-horizon loop
            _saved = factor in tester.results
            _saved_freq = tester.results.get(factor, FactorRunResult()).return_freq
            _saved_returns = tester.results.get(factor, FactorRunResult()).returns.copy() if _saved else pd.DataFrame()
            
            multi_horizon_results = []
            for rf_str in return_freqs:
                try:
                    freq = DataFreq(rf_str) if rf_str else None
                except Exception:
                    freq = None
                r = tester._get_result(factor)
                if freq is not None:
                    r.return_freq = freq
                else:
                    r.return_freq = None
                r.returns = pd.DataFrame()
                _, _returns_dict, report_df, cum_np, idx_list = tester.test_by_group(
                    factors=factor, n_groups=n_groups, time_range=time_range,
                    plot_flag=False, save_plot=False, plot_show=False,
                    fee=fee_uniform, fee_map=fee_map,
                    use_closetoday=use_closetoday,
                    rebalance_mode=rebalance_mode,
                    derived_groups=data.get('derived_groups'),
                    group_fee_maps=data.get('group_fee_maps'),
                )
                # ... (computation logic unchanged) ...
                timestamps = [to_utc_epoch(_signal_time(d)) for d in idx_list]
                group_result = tester._get_result(factor).group_result
                _gross = group_result.gross_returns_np if group_result is not None else None
                gross_np = _gross if _gross is not None else np.zeros((len(timestamps), n_groups))
                _fee_np = group_result.fee_costs_np if group_result is not None else None
                fee_np_arr = _fee_np if _fee_np is not None else np.zeros((len(timestamps), n_groups))

                r_ls_np, _ = _compute_weighted_ls_returns(gross_np, fee_np_arr, ls_configs[0], n_groups) if ls_configs else (np.array([]), np.array([]))
                ls_metric = _compute_ls_metrics(r_ls_np, report_df, idx_list) if ls_configs else {}
                freq_label = str(rf_str) if rf_str else factor.freq.name if factor.freq else 'base'
                multi_horizon_results.append({
                    'return_freq': freq_label,
                    'ls_metrics': ls_metric,
                    'report': report_df.to_dict(orient='index') if not report_df.empty else {},
                })
            
            # Restore original FactorRunResult state after multi-horizon loop
            if factor in tester.results:
                tester.results[factor].return_freq = _saved_freq
                tester.results[factor].returns = _saved_returns
            
            _gr = tester._get_result(factor).group_result  # local ref for type narrowing
            return jsonify({'success': True, 'multi_horizon': True, 'results': multi_horizon_results, 'n_groups': n_groups,
                            'structure_key': data.get('structure_key'),
                            'multi_session_active': bool(_gr.multi_session_active) if _gr is not None else False,
                            'rebalance_mode': rebalance_mode,
                            'submission_id': submission_id, 'factor_alias': factor_alias,
                            'tester_alias': getattr(tester, 'alias', '?'),
                            'tester_product_count': len(tester.products) if hasattr(tester, 'products') else 0})

        # ─── 原有单频率逻辑 ───
        # DEBUG: log which tester is serving this request
        tester_id = getattr(tester, 'alias', '?')
        _log.info("run_group_test: submission_id=%s tester.alias=%s factor=%s n_products=%d",
                  submission_id, tester_id, factor_alias, len(tester.products) if hasattr(tester, 'products') else 0)

        _, _returns_dict, report_df, cum_np, idx_list = tester.test_by_group(
            factors=factor, n_groups=n_groups, time_range=time_range,
            plot_flag=False, save_plot=False, plot_show=False,
            fee=fee_uniform, fee_map=fee_map,
            use_closetoday=use_closetoday,
            rebalance_mode=rebalance_mode,
            derived_groups=data.get('derived_groups'),
            group_fee_maps=data.get('group_fee_maps'),
        )

        timestamps = [to_utc_epoch(_signal_time(d)) for d in idx_list]

        group_result = tester._get_result(factor).group_result
        n_total = group_result.returns_np.shape[1] if group_result is not None else n_groups
        n_base = getattr(group_result, 'n_base', n_groups) or n_groups
        n_derived = getattr(group_result, 'n_derived', 0) or 0
        derived_info = getattr(group_result, 'derived_info', None) or []
        _gross = group_result.gross_returns_np if group_result is not None else None
        gross_np = _gross if _gross is not None else np.zeros((len(timestamps), n_total))
        _fee = group_result.fee_costs_np if group_result is not None else None
        fee_np = _fee if _fee is not None else np.zeros((len(timestamps), n_total))

        groups_data = []
        for g in range(n_total):
            is_derived = g >= n_base
            vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else None for v in cum_np[:, g]]
            gross_vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else 0.0 for v in gross_np[:, g]]
            fee_vals   = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else 0.0 for v in fee_np[:, g]]
            entry = {
                'key': _group_display_key(g, n_base, derived_info),
                'name': f'Group {g+1}',
                'group_index': g,
                'timestamps': timestamps,
                'cumulative_returns': vals,
                'gross_returns': gross_vals,
                'fee_costs': fee_vals,
                'trade_notional_ratios': [
                    round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else 0.0
                    for v in group_result.trade_notional_ratio_np[:, g]
                ] if group_result is not None and group_result.trade_notional_ratio_np is not None else [],
            }
            if is_derived:
                di = derived_info[g - n_base]
                entry['name'] = di.get('name', entry['name'])
                entry['is_derived'] = True
                entry['derived'] = {
                    'base_group': di['base_group'],
                    'product_names': di['product_names'],
                    'id': di.get('id'),
                }
            groups_data.append(entry)

        metrics: dict = {}
        # 建立派生组索引→名称的映射（用于 metrics key 替换）
        _derived_name_map: dict = {}
        for di_idx, di in enumerate(derived_info):
            _derived_name_map[n_base + di_idx] = di.get('name', f'第{n_base + di_idx + 1}组精选')
        if not report_df.empty:
            raw_metrics = report_df.to_dict(orient='index')
            for k, v in raw_metrics.items():
                display_key = _metric_display_key(k, n_base, derived_info)
                metrics[display_key] = {
                    mk: (None if mv is None or (isinstance(mv, float) and (math.isnan(mv) or math.isinf(mv))) else float(mv))
                    for mk, mv in v.items()
                }
        used_keys = set(metrics.keys())
        for ls_config in ls_configs:
            r_ls, ls_cum_arr = _compute_weighted_ls_returns(gross_np, fee_np, ls_config, n_total)
            ls_name = ls_config['name'] or 'Long-Short'
            ls_key = _unique_group_key(ls_name, used_keys)
            ls_vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else None for v in ls_cum_arr]
            groups_data.append({
                'key': ls_key,
                'name': ls_name,
                'timestamps': timestamps,
                'cumulative_returns': ls_vals,
                'gross_returns': _serialize_float_series(r_ls, default=0.0),
                'fee_costs': [0.0] * len(r_ls),
                'trade_notional_ratios': [0.0] * len(r_ls),
                'is_ls': True,
                'is_derived': True,
                'derived': {'type': 'long_short', 'key': ls_key, 'config': ls_config},
            })
            metrics[ls_key] = _compute_ls_metrics(r_ls, report_df, idx_list)

        return jsonify({'success': True, 'groups': groups_data, 'metrics': metrics, 'n_groups': n_total,
                        'n_base': n_base,
                        'structure_key': data.get('structure_key'),
                        'multi_session_active': bool(group_result.multi_session_active) if group_result is not None else False,
                        'rebalance_mode': rebalance_mode,
                        'submission_id': submission_id, 'factor_alias': factor_alias,
                        'tester_alias': getattr(tester, 'alias', '?'),
                        'tester_product_count': len(tester.products) if hasattr(tester, 'products') else 0})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})
    finally:
        if _saved_products is not None and tester is not None:
            tester.products = _saved_products
        if _gt_token is not None:
            _active_tester.reset(_gt_token)


@sft_bp.route('/get_group_snapshot', methods=['POST'])
def get_group_snapshot():
    """获取某个时刻各分组的产品列表及与上一时刻的进出变化。
    
    请求参数：
        submission_id : 提交 ID
        timestamp_ms  : 目标时刻（UTC epoch 毫秒）
    
    返回：{
        groups: [{
            name, 
            products: [...],        // 当前持仓
            products_in: [...],     // 新进（上一时刻没有，当前有）
            products_out: [...],    // 退出（上一时刻有，当前没有）
            turnover_rate: float,   // 换手率
        }, ...]
    }
    """
    data = request.get_json()
    submission_id = data.get('submission_id')
    timestamp_ms  = data.get('timestamp_ms')
    if not submission_id or not timestamp_ms:
        return jsonify({'success': False, 'error': '缺少 submission_id 或 timestamp_ms'}), 400

    try:
        tester = runtime_state.get_factor_tester(submission_id, caller='get_group_snapshot')

        group_result = _latest_group_result(tester)
        products_dict = group_result.products_by_group if group_result is not None else None
        valid_cols_raw = group_result.valid_cols if group_result is not None else None
        if not products_dict or not _safe_bool(valid_cols_raw):
            return jsonify({'success': False, 'error': '未找到最近的分组测试结果，请先运行分组测试'}), 400
        valid_cols = valid_cols_raw

        # 找到最接近的时刻
        # products_dict: {group_idx: {index_entry: [product_names]}}
        # index_entry 可能是 Timestamp 或 tuple
        first_group = next(iter(products_dict.values()))
        all_times = []
        for idx_entry in first_group.keys():
            ts = _signal_time(idx_entry)
            # 统一转为 naive epoch 秒用于比较
            if isinstance(ts, pd.Timestamp):
                ts_no_tz_untyped = ts.tz_localize(None) if ts.tzinfo else ts
                ts_epoch = pd.Timestamp(ts_no_tz_untyped).value // 10**9
            elif hasattr(ts, 'timestamp'):
                ts_epoch = pd.Timestamp(ts).value // 10**9
            else:
                ts_epoch = float(ts)
            all_times.append((ts_epoch, idx_entry))

        # 前端传来的 UTC epoch 毫秒
        target_epoch = float(timestamp_ms) / 1000.0

        # 找最近的
        best_idx_entry = None
        best_diff = float('inf')
        for ts_epoch, idx_entry in all_times:
            diff = abs(ts_epoch - target_epoch)
            if diff < best_diff:
                best_diff = diff
                best_idx_entry = idx_entry

        if best_idx_entry is None:
            return jsonify({'success': False, 'error': '未找到匹配的时间点'}), 404

        # 找到上一时刻 — 用 all_times 的 epoch 排序（避免 tuple/array 直接比较）
        # 用 enumerate 添加位置索引作为 tiebreaker，防止 sorted 回退到 tuple 比较
        # （idx_entry 可能为包含 numpy 类型的 tuple，其 __eq__ 会触发 ambiguous truth value）
        sorted_times = [item for _, item in sorted(enumerate(all_times), key=lambda pair: (pair[1][0], pair[0]))]
        sorted_entries = [item[1] for item in sorted_times]
        current_pos = None
        for pos, (_, entry) in enumerate(sorted_times):
            if entry is best_idx_entry:
                current_pos = pos
                break
        if current_pos is None:
            current_pos = 0
        prev_entry = sorted_entries[current_pos - 1] if current_pos > 0 else None

        n_groups = len(products_dict)
        fee_rates_by_name = _product_fee_rates_by_name(group_result)
        groups_detail = []
        for g in range(n_groups):
            current_raw = products_dict[g].get(best_idx_entry, [])
            current_display = [_display_product_with_fee(x, fee_rates_by_name) for x in current_raw]
            # 按 name 排序
            current_display.sort(key=lambda d: d['name'])

            if prev_entry is not None:
                prev_raw = products_dict[g].get(prev_entry, [])
                prev_display = [_display_product_with_fee(x, fee_rates_by_name) for x in prev_raw]
                prev_names = set(d['name'] for d in prev_display)
                curr_names = set(d['name'] for d in current_display)

                in_names = sorted(curr_names - prev_names)
                out_names = sorted(prev_names - curr_names)

                # 新进/退出：从 current_display / prev_display 中查找完整信息
                _name_map = {d['name']: d for d in current_display}
                _prev_name_map = {d['name']: d for d in prev_display}
                products_in = [_name_map[n] for n in in_names]
                products_out = [_prev_name_map[n] for n in out_names]

                prev_count = len(prev_raw)
                curr_count = len(current_raw)
                avg_count = (prev_count + curr_count) / 2.0
                changed = len(in_names) + len(out_names)
                turnover_rate = round(changed / (2.0 * avg_count), 4) if avg_count > 0 else 0.0
            else:
                products_in = []
                products_out = []
                turnover_rate = 0.0

            groups_detail.append({
                'name': f'Group {g+1}',
                'products': current_display,
                'products_in': products_in,
                'products_out': products_out,
                'turnover_rate': turnover_rate,
                'count': len(current_display),
            })

        # 所有时间点（epoch 毫秒），用于前/后导航
        all_timestamps_ms = sorted(set(
            int(ts_epoch * 1000) for ts_epoch, _idx in all_times
        ))
        # 用最接近的 all_timestamps_ms 条目（而非前端传来的不精确 timestamp_ms）
        closest_ms = min(all_timestamps_ms, key=lambda x: abs(x - int(timestamp_ms)))
        current_index = all_timestamps_ms.index(closest_ms)

        return jsonify({
            'success': True,
            'groups': groups_detail,
            'timestamp_ms': closest_ms,
            'has_prev': prev_entry is not None,
            'has_next': current_index >= 0 and current_index < len(all_timestamps_ms) - 1,
            'all_timestamps_ms': all_timestamps_ms,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})


@sft_bp.route('/get_group_detail', methods=['POST'])
def get_group_detail():
    """Return first-phase detail analytics for one group from the latest run."""
    data = request.get_json() or {}
    submission_id = data.get('submission_id')
    group_index = data.get('group_index')
    if submission_id is None or group_index is None:
        return jsonify({'success': False, 'error': '缺少 submission_id 或 group_index'}), 400
    try:
        group_index = int(group_index)
        tester = runtime_state.get_factor_tester(submission_id, caller='get_group_detail')
        group_result = _latest_group_result(tester)
        products = group_result.products_by_group if group_result is not None else None
        returns_np = group_result.returns_np if group_result is not None else None
        product_contrib_np = group_result.product_gross_contrib_np if group_result is not None else None
        gross_returns_np = group_result.gross_returns_np if group_result is not None else None
        trade_notional_np = group_result.trade_notional_ratio_np if group_result is not None else None
        valid_cols = group_result.valid_cols if group_result is not None else None
        index_list = group_result.index_list if group_result is not None else None
        if not products or returns_np is None or not index_list:
            return jsonify({'success': False, 'error': '未找到最近的分组测试结果，请先运行分组测试'}), 400
        if group_index < 0 or group_index >= returns_np.shape[1]:
            return jsonify({'success': False, 'error': '分组索引无效'}), 400
        metrics = group_result.report_df if group_result is not None else None
        summary = {}
        if isinstance(metrics, pd.DataFrame) and group_index in metrics.index:
            summary = {
                str(key): _safe_float(value)
                for key, value in metrics.loc[group_index].to_dict().items()
            }
        detail = build_group_detail(
            group_index, products, returns_np, index_list, summary,
            product_contrib_np, valid_cols, gross_returns_np, trade_notional_np,
            group_result.fee_costs_np if group_result is not None else None,
            group_result.open_fee_vec if group_result is not None else None,
            group_result.close_fee_vec if group_result is not None else None,
            group_result.close_today_fee_vec if group_result is not None else None,
        )
        return jsonify({'success': True, 'detail': detail})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})


@sft_bp.route('/create_derived_groups_batch', methods=['POST'])
def create_derived_groups_batch():
    """批量生成多个派生组（一次调用，后端一次 simulate_groups 计算同基础组的所有派生组）。"""
    data = request.get_json() or {}
    submission_id = data.get('submission_id')
    entries = data.get('entries') or []  # [{group_index, product_names, name}, ...]
    use_closetoday = bool(data.get('use_closetoday', False))
    if submission_id is None or not entries:
        return jsonify({'success': False, 'error': '缺少 submission_id 或 entries'}), 400
    try:
        tester = runtime_state.get_factor_tester(submission_id, caller='create_derived_groups_batch')
        group_result = _latest_group_result(tester)
        if group_result is None:
            return jsonify({'success': False, 'error': '未找到最近的分组测试结果，请先运行分组测试'}), 400
        fee_uniform, fee_map, _ = _parse_group_fee_config(data, getattr(tester, 'products', None))
        results = _build_derived_groups_batch_payload(
            group_result, entries,
            use_closetoday=use_closetoday, fee_map=fee_map, fee_uniform=fee_uniform,
        )
        return jsonify({'success': True, 'results': results})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})


@sft_bp.route('/create_derived_group', methods=['POST'])
def create_derived_group():
    """Create a chart/metric payload for a user-defined product subset group."""
    data = request.get_json() or {}
    submission_id = data.get('submission_id')
    group_index = data.get('group_index')
    product_names = data.get('product_names') or []
    name = str(data.get('name') or '').strip()
    use_closetoday = bool(data.get('use_closetoday', False))
    fee_override = data.get('fee_override')
    if submission_id is None or group_index is None:
        return jsonify({'success': False, 'error': '缺少 submission_id 或 group_index'}), 400
    try:
        tester = runtime_state.get_factor_tester(submission_id, caller='create_derived_group')
        group_result = _latest_group_result(tester)
        if group_result is None:
            return jsonify({'success': False, 'error': '未找到最近的分组测试结果，请先运行分组测试'}), 400
        # 从请求中解析费率（与 run_group_test 相同的 _parse_group_fee_config）
        fee_uniform, fee_map, _ = _parse_group_fee_config(data, getattr(tester, 'products', None))
        group, metric = _build_derived_group_payload(
            group_result,
            int(group_index),
            [str(x) for x in product_names],
            name or f'第{int(group_index) + 1}组精选',
            use_closetoday=use_closetoday,
            fee_map=fee_map,
            fee_uniform=fee_uniform,
            fee_override=fee_override,
        )
        return jsonify({'success': True, 'group': group, 'metric': metric})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})


@sft_bp.route('/get_group_ranking_detail', methods=['POST'])
def get_group_ranking_detail():
    """Return second-phase whole-test ranking analytics from the latest run."""
    data = request.get_json() or {}
    submission_id = data.get('submission_id')
    if submission_id is None:
        return jsonify({'success': False, 'error': '缺少 submission_id'}), 400
    try:
        tester = runtime_state.get_factor_tester(submission_id, caller='get_group_ranking_detail')
        group_result = _latest_group_result(tester)
        returns_np = group_result.returns_np if group_result is not None else None
        index_list = group_result.index_list if group_result is not None else None
        if returns_np is None:
            return jsonify({'success': False, 'error': '未找到最近的分组测试结果，请先运行分组测试'}), 400
        return jsonify({'success': True, 'detail': build_group_ranking_detail(returns_np, index_list)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})


# ─────────────────────────────────────────────
#  Issue #85: 批量分组任务端点
# ─────────────────────────────────────────────

def _merge_tasks_by_triple(run_tasks: list[dict]) -> dict[tuple, list[dict]]:
    """按三元组 (submission_id, factor_alias, n_groups) 合并去重。

    返回 {triple: [task, ...]}，同一三元组只执行一次 test_by_group。
    """
    groups: dict[tuple, list[dict]] = {}
    for task in run_tasks:
        if not isinstance(task, dict):
            continue
        sid = str(task.get('submission_id', ''))
        fa  = str(task.get('factor_alias', ''))
        ng  = int(task.get('n_groups', 5))
        triple = (sid, fa, ng)
        groups.setdefault(triple, []).append(task)
    return groups


def _execute_single_triple(tester, factor, triple: tuple, tasks: list[dict]) -> dict:
    """对单个三元组执行 test_by_group，然后为每个 task 计算其 LS/派生组。"""
    n_groups = triple[2]
    first = tasks[0]
    start_date = first.get('start_date')
    end_date   = first.get('end_date')

    # 解析费率
    fee_uniform, fee_map, use_closetoday = _parse_group_fee_config(first, getattr(tester, 'products', None))
    rebalance_mode = str(first.get('rebalance_mode', 'buy_and_hold') or 'buy_and_hold')

    time_range = None
    if start_date and end_date:
        start_dt = pd.to_datetime(start_date)
        end_dt   = pd.to_datetime(end_date)
        tz = getattr(tester.start_date, 'tz', None) if hasattr(tester.start_date, 'tz') else None
        if tz:
            if start_dt.tzinfo is None: start_dt = start_dt.tz_localize(tz)
            if end_dt.tzinfo is None:   end_dt   = end_dt.tz_localize(tz)
        time_range = (start_dt, end_dt)

    # 收集所有 task 的派生组配置（合并去重）
    all_derived: list[dict] = []
    seen_dg: set = set()
    for t in tasks:
        for dg in (t.get('derived_groups') or []):
            if not isinstance(dg, dict):
                continue
            key = (dg.get('base_group'), tuple(dg.get('product_names') or []))
            if key not in seen_dg:
                seen_dg.add(key)
                all_derived.append(dg)

    # 执行一次 test_by_group
    _gt_token = _active_tester.set(tester)
    _saved_products = tester.products.copy()
    tester.products = set(_saved_products)
    try:
        _, _returns_dict, report_df, cum_np, idx_list = tester.test_by_group(
            factors=factor, n_groups=n_groups, time_range=time_range,
            plot_flag=False, save_plot=False, plot_show=False,
            fee=fee_uniform, fee_map=fee_map,
            use_closetoday=use_closetoday,
            rebalance_mode=rebalance_mode,
            derived_groups=all_derived if all_derived else None,
        )
    finally:
        tester.products = _saved_products
        _active_tester.reset(_gt_token)

    timestamps = [to_utc_epoch(_signal_time(d)) for d in idx_list]
    group_result = tester._get_result(factor).group_result
    n_total = group_result.returns_np.shape[1] if group_result is not None else n_groups
    n_base = getattr(group_result, 'n_base', n_groups) or n_groups
    n_derived = getattr(group_result, 'n_derived', 0) or 0
    derived_info = getattr(group_result, 'derived_info', None) or []
    _gross = group_result.gross_returns_np if group_result is not None else None
    gross_np = _gross if _gross is not None else np.zeros((len(timestamps), n_total))
    _fee = group_result.fee_costs_np if group_result is not None else None
    fee_np = _fee if _fee is not None else np.zeros((len(timestamps), n_total))

    # 构建共享的 groups_data + metrics
    groups_data = []
    for g in range(n_total):
        is_derived = g >= n_base
        vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else None for v in cum_np[:, g]]
        gross_vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else 0.0 for v in gross_np[:, g]]
        fee_vals   = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else 0.0 for v in fee_np[:, g]]
        entry = {
            'key': _group_display_key(g, n_base, derived_info),
            'name': f'Group {g+1}',
            'group_index': g,
            'timestamps': timestamps,
            'cumulative_returns': vals,
            'gross_returns': gross_vals,
            'fee_costs': fee_vals,
            'trade_notional_ratios': [
                round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else 0.0
                for v in group_result.trade_notional_ratio_np[:, g]
            ] if group_result is not None and group_result.trade_notional_ratio_np is not None else [],
        }
        if is_derived:
            di = derived_info[g - n_base]
            entry['name'] = di.get('name', entry['name'])
            entry['is_derived'] = True
            entry['derived'] = {
                'base_group': di['base_group'],
                'product_names': di['product_names'],
                'id': di.get('id'),
            }
        groups_data.append(entry)

    metrics: dict = {}
    _derived_name_map: dict = {}
    for di_idx, di in enumerate(derived_info):
        _derived_name_map[n_base + di_idx] = di.get('name', f'第{n_base + di_idx + 1}组精选')
    if not report_df.empty:
        raw_metrics = report_df.to_dict(orient='index')
        for k, v in raw_metrics.items():
            display_key = _metric_display_key(k, n_base, derived_info)
            metrics[display_key] = {
                mk: (None if mv is None or (isinstance(mv, float) and (math.isnan(mv) or math.isinf(mv))) else float(mv))
                for mk, mv in v.items()
            }

    # 为每个 task 计算其 LS 指标
    task_results = []
    for task in tasks:
        ls_configs = _parse_ls_configs(task, n_groups)
        ls_metrics_list = []
        for ls_config in ls_configs:
            r_ls, ls_cum_arr = _compute_weighted_ls_returns(gross_np, fee_np, ls_config, n_total)
            ls_metric = _compute_ls_metrics(r_ls, report_df, idx_list)
            ls_metrics_list.append({
                'name': ls_config['name'],
                'metrics': ls_metric,
            })
        task_results.append({
            'task_index': task.get('_task_index'),
            'ls_metrics': ls_metrics_list,
        })

    return {
        'triple': list(triple),
        'groups': groups_data,
        'metrics': metrics,
        'n_groups': n_total,
        'n_base': n_base,
        'task_results': task_results,
        'multi_session_active': bool(group_result.multi_session_active) if group_result is not None else False,
        'rebalance_mode': rebalance_mode,
    }


@sft_bp.route('/run_group_tasks', methods=['POST'])
def run_group_tasks():
    """批量执行分组测试任务。

    请求：{
        run_tasks: [
            {submission_id, factor_alias, n_groups, rebalance_mode,
             fee, fee_map, use_closetoday, start_date, end_date,
             derived_groups, ls_configs}
        ]
    }

    按三元组 (submission_id, factor_alias, n_groups) 合并去重，同一三元组只执行一次 test_by_group。
    返回按三元组分组的完整结果 + 每个 task 独立的 LS 指标。
    """
    data = request.get_json() or {}
    run_tasks: list = data.get('run_tasks', [])
    if not run_tasks:
        return jsonify({'success': False, 'error': '缺少 run_tasks 列表'}), 400

    # 标记 task 原始索引
    for i, task in enumerate(run_tasks):
        if isinstance(task, dict):
            task['_task_index'] = i

    triple_groups = _merge_tasks_by_triple(run_tasks)
    triple_results = []

    for triple, tasks in triple_groups.items():
        submission_id = triple[0]
        factor_alias = triple[1]
        n_groups = triple[2]
        try:
            tester = runtime_state.get_factor_tester(submission_id, caller='run_group_tasks')
            factor = next((f for f in tester.factors if f.alias == factor_alias or f.name == factor_alias), None)
            if not factor:
                if not getattr(tester, 'factors', None):
                    triple_results.append({
                        'triple': list(triple),
                        'error': '当前测试器尚未生成因子实例。请先在 IC 测试模块运行一次 IC 测试。',
                        'needs_ic_test': True,
                    })
                else:
                    triple_results.append({
                        'triple': list(triple),
                        'error': f'未找到因子 {factor_alias}',
                    })
                continue

            result = _execute_single_triple(tester, factor, triple, tasks)
            result['submission_id'] = submission_id
            result['factor_alias'] = factor_alias
            result['tester_alias'] = getattr(tester, 'alias', '?')
            result['tester_product_count'] = len(tester.products) if hasattr(tester, 'products') else 0
            triple_results.append(result)
        except Exception as e:
            triple_results.append({
                'triple': list(triple),
                'error': str(e),
                'traceback': traceback.format_exc(),
            })

    return jsonify({'success': True, 'triple_results': triple_results})


@sft_bp.route('/get_tester_session_info', methods=['POST'])
def get_tester_session_info():
    """返回测试器会话摘要信息（供第3层策略通知表格使用）。

    请求：{submission_ids: [str, ...]}  或  {submission_id: str}

    返回：{
        testers: [{
            submission_id, tester_alias, product_count,
            factors: [{
                alias, name, freq,
                n_groups: int,   // 上次分组测试用的组数
                rebalance_mode,  // 上次使用的再平衡模式
                has_results: bool,
            }]
        }]
    }
    """
    data = request.get_json() or {}
    ids = data.get('submission_ids') or []
    if not ids and data.get('submission_id'):
        ids = [data['submission_id']]
    if not ids:
        return jsonify({'success': False, 'error': '缺少 submission_ids'}), 400

    testers_info = []
    for sid in ids:
        try:
            tester = runtime_state.find_factor_tester(str(sid), allow_suffix=True)
            if tester is None:
                testers_info.append({'submission_id': str(sid), 'error': '未找到测试器实例'})
                continue
            factors_info = []
            for f in (getattr(tester, 'factors', None) or []):
                info = {
                    'alias': getattr(f, 'alias', None) or getattr(f, 'name', '?'),
                    'name': getattr(f, 'name', '?'),
                    'freq': f.freq.name if hasattr(f, 'freq') and f.freq else None,
                }
                # 如果该因子有上次分组测试的结果
                result = tester.results.get(f) if hasattr(tester, 'results') else None
                if result is not None and result.group_result is not None:
                    gr = result.group_result
                    info['n_groups'] = getattr(gr, 'n_base', None)
                    info['rebalance_mode'] = getattr(gr, 'rebalance_mode', None)
                    info['has_results'] = True
                else:
                    info['has_results'] = False
                factors_info.append(info)
            testers_info.append({
                'submission_id': str(sid),
                'tester_alias': getattr(tester, 'alias', '?'),
                'product_count': len(tester.products) if hasattr(tester, 'products') else 0,
                'factors': factors_info,
            })
        except Exception as e:
            testers_info.append({'submission_id': str(sid), 'error': str(e)})

    return jsonify({'success': True, 'testers': testers_info})
