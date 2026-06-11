"""Group test endpoint."""
import logging, math, time, traceback
from typing import Any, cast
import numpy as np
import pandas as pd
from flask import request, jsonify
from tools.factors.FactorTester import FactorTester, _active_tester, _signal_time
from tools.factors.tests.single_factor_test.group.core import infer_periods_per_year
from tools.factors.tests.single_factor_test.group.detail import build_group_detail
from tools.factors.tests.single_factor_test.group.monotonicity import build_group_ranking_detail
from . import sft_bp
import server.services.runtime_state as runtime_state
from server.modules.shared.price_data_helpers import to_epoch_ms

_log = logging.getLogger(__name__)


def _progress(message: str) -> None:
    print(f"[GroupTest] {message}", flush=True)


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


def _parse_initial_capital(raw: Any, default: float = 100000000.0) -> float:
    """Parse initial capital with a stable backend default."""
    if raw in (None, ''):
        return float(default)
    value = _safe_float(raw)
    if value is None or value <= 0:
        raise ValueError(f'初始金额必须是正数，收到: {raw!r}')
    return float(value)


def _build_zero_position_warning(group_result: Any) -> str | None:
    """Explain when the first rebalance cannot open any position."""
    if group_result is None:
        return None
    quantities = getattr(group_result, 'position_quantities_np', None)
    membership = getattr(group_result, 'membership_np', None)
    initial_capital = getattr(group_result, 'initial_capital', None)
    if quantities is None or membership is None:
        return None
    if getattr(quantities, 'size', 0) == 0 or getattr(membership, 'size', 0) == 0:
        return None
    first_membership = np.asarray(membership[0], dtype=bool)
    first_quantities = np.asarray(quantities[0], dtype=float)
    wants_position = first_membership.any(axis=1)
    has_position = np.any(np.abs(first_quantities) > 1e-12, axis=1)
    blocked = np.where(wants_position & (~has_position))[0]
    if blocked.size == 0:
        return None
    capital_text = f"{float(initial_capital):,.0f}" if isinstance(initial_capital, (int, float)) else "当前值"
    return (
        f"首期有 {int(blocked.size)} 个组未能开出任何仓位。"
        f"这通常是初始金额 {capital_text} 仍不足以覆盖合约乘数、最小交易手数、手续费或保证金造成的。"
    )


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


def _parse_group_names_payload(group_names) -> dict[int, str]:
    """Parse frontend group names into a plain group-index -> display-name mapping."""
    if not isinstance(group_names, dict):
        return {}
    n_groups_name: dict[int, str] = {}
    for key, value in group_names.items():
        try:
            g = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, dict):
                display_name = first.get('key') or first.get('shortAlias') or first.get('name') or f'group_{g}'
                n_groups_name[g] = str(display_name)
            else:
                n_groups_name[g] = str(first)
        else:
            n_groups_name[g] = str(value)
    return n_groups_name


def _parse_groups_payload(groups_payload) -> tuple[dict[int, str], dict[int, list[dict]] | None]:
    """Parse flat frontend group payloads into group-name and variant mappings."""
    if not isinstance(groups_payload, list):
        return {}, None
    grouped: dict[int, list[dict]] = {}
    names: dict[int, str] = {}
    for item in groups_payload:
        if not isinstance(item, dict):
            continue
        # 子组（有 parentId/parent_id）不在 variant mapping 中处理 —— 走 _extract_derived_groups_from_payload
        if item.get('parentId') or item.get('parent_id'):
            continue
        try:
            g = int(item.get('group_index', item.get('groupIndex', 0)))
        except (TypeError, ValueError):
            continue
        display_name = item.get('key') or item.get('shortAlias') or item.get('name') or f'group_{g}'
        variant = {
            'name': str(display_name),
            'key': str(display_name),
            'fee_map': item.get('fee_map') or item.get('feeMap') or None,
            'fee_mode': item.get('fee_mode') or item.get('feeMode') or None,
            'fee_rate': item.get('fee_rate', item.get('feeRate')),
            'use_close_today': item.get('use_close_today', item.get('useCloseToday')),
            'rebalance_mode': item.get('rebalance_mode') or item.get('rebalanceMode') or None,
            'liquidity_mode': item.get('liquidity_mode') or item.get('liquidityMode') or None,
            'liquidity_percent': item.get('liquidity_percent', item.get('liquidityPercent')),
            'margin_mode': item.get('margin_mode') or item.get('marginMode') or None,
        }
        grouped.setdefault(g, []).append(variant)
        names.setdefault(g, str(display_name))
    return names, grouped or None


def _extract_derived_groups_from_payload(
    groups_payload, n_groups_name: dict[int, str] | None = None
) -> list[dict] | None:
    """从扁平的 groups 数组中提取子组（有 parentId 的条目）。

    每个子组需要 base_group（指向基组索引，按 groupIndex/gid）、
    product_names（从 productMask 或 productNames 提取），以及元数据。
    """
    if not isinstance(groups_payload, list):
        return None

    # 第一遍：为所有组建立 id → groupIndex 映射
    gid_to_index: dict[str, int] = {}
    for item in groups_payload:
        if not isinstance(item, dict):
            continue
        gid = item.get('id')
        idx = item.get('groupIndex')
        if gid and isinstance(idx, (int, float)):
            gid_to_index[str(gid)] = int(idx) - 1  # groupIndex 是 1-based

    derived = []
    for item in groups_payload:
        if not isinstance(item, dict):
            continue
        if not item.get('parentId'):
            continue

        base_group = None
        # Walk parentId chain to find root and use its groupIndex
        parent_id = item.get('parentId')
        if parent_id:
            root_idx = gid_to_index.get(str(parent_id))
            if root_idx is None:
                # parent not in gid_to_index, try groupIndex as fallback
                idx = item.get('groupIndex')
                if isinstance(idx, (int, float)):
                    base_group = int(idx) - 1
            else:
                base_group = root_idx

        if base_group is None:
            continue

        # 提取产品列表
        product_names = _extract_product_names_from_group(item)

        display_name = (
            item.get('shortAlias')
            or item.get('name')
            or item.get('key')
            or f'第{base_group + 1}组精选'
        )

        entry = {
            'name': str(display_name),
            'key': str(display_name),
            'base_group': base_group,
            'group_index': base_group,
            'product_names': product_names,
        }
        # 额外转发配置字段
        for src, dst in [
            ('feeMode', 'fee_mode'), ('feeRate', 'fee_rate'), ('feeMap', 'fee_map'),
            ('useCloseToday', 'use_close_today'),
            ('rebalanceMode', 'rebalance_mode'), ('liquidityMode', 'liquidity_mode'),
            ('liquidityPercent', 'liquidity_percent'), ('marginMode', 'margin_mode'),
        ]:
            val = item.get(src)
            if val is not None:
                entry[dst] = val
        derived.append(entry)

    return derived if derived else None


def _extract_product_names_from_group(group: dict) -> list[str]:
    """从 group 对象中提取产品名列表（扁平化 productMask → 产品名数组）."""
    # 优先用 productNames（已经是数组）
    pn = group.get('productNames')
    if isinstance(pn, list) and pn:
        return [str(n) for n in pn]

    # productMask: { productName: true/false }
    mask = group.get('productMask')
    if isinstance(mask, dict):
        return sorted([str(k) for k, v in mask.items() if v])

    return []


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
    gross_np = np.nan_to_num(np.asarray(gross_np, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    fee_np = np.nan_to_num(np.asarray(fee_np, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    legs = []
    for leg in ls_config.get('long') or []:
        if 0 <= leg['group'] < n_groups:
            legs.append({'side': 1.0, 'group': leg['group'], 'cap': leg['weight']})
    for leg in ls_config.get('short') or []:
        if 0 <= leg['group'] < n_groups:
            legs.append({'side': -1.0, 'group': leg['group'], 'cap': leg['weight']})
    if not legs:
        legs = [{'side': 1.0, 'group': 0, 'cap': 0.5}, {'side': -1.0, 'group': n_groups - 1, 'cap': 0.5}]

    initial_caps = np.array([float(leg['cap']) for leg in legs], dtype=float)
    groups = np.array([int(leg['group']) for leg in legs], dtype=int)
    sides = np.array([float(leg['side']) for leg in legs], dtype=float)

    leg_gross = gross_np[:, groups] * sides[np.newaxis, :]
    leg_fee = fee_np[:, groups]
    leg_net = (1.0 - leg_fee) * (1.0 + leg_gross) - 1.0
    leg_net = np.where(np.isfinite(leg_net), leg_net, 0.0)

    leg_caps = initial_caps[np.newaxis, :] * np.cumprod(1.0 + leg_net, axis=0)
    total_caps = np.nansum(leg_caps, axis=1)
    previous_total_caps = np.concatenate([[np.nansum(initial_caps) or 1.0], total_caps[:-1]])
    r_ls = np.divide(
        total_caps,
        previous_total_caps,
        out=np.ones_like(total_caps, dtype=float),
        where=np.abs(previous_total_caps) > 1e-12,
    ) - 1.0
    r_ls = np.where(np.isfinite(r_ls), r_ls, 0.0)
    total_caps = np.where(np.isfinite(total_caps), total_caps, previous_total_caps)
    return r_ls.astype(float), total_caps.astype(float)


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

    timestamps = [to_epoch_ms(_signal_time(d), use_utc=True) for d in idx_list]
    metric = _compute_return_metrics(sim['net_returns'], index_like=idx_list, avg_turnover=None)

    group = {
        'name': name or f'第{group_index + 1}组精选',
        'timestamps': timestamps,
        'total_equity': _serialize_float_series(sim['total_equity'], default=0.0),
        'gross_returns': _serialize_float_series(sim['gross_returns'], default=0.0),
        'fee_costs': _serialize_float_series(sim['fee_costs'], default=0.0),
        'trade_notional_ratios': _serialize_float_series(sim['notional_ratios'], default=0.0),
        'parent_id': group_index,
        'product_names': [display_names[idx] for idx in selected_idx],
    }
    return group, metric


def _build_derived_groups_batch_payload(group_result, entries: list[dict],
                                         use_closetoday: bool = False,
                                         fee_map: dict | None = None,
                                         fee_uniform: float = 0.0) -> list[dict]:
    """一次 simulate_derived_groups_batch 调用，返回 [{success, group?, metric?, error?}, ...]。

    同一 group_index 的条目合并为一次精选组交易簿模拟调用。
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
    timestamps = [to_epoch_ms(_signal_time(d), use_utc=True) for d in idx_list]

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
                        'total_equity': _serialize_float_series(sim['total_equity'], default=0.0),
                        'gross_returns': _serialize_float_series(sim['gross_returns'], default=0.0),
                        'fee_costs': _serialize_float_series(sim['fee_costs'], default=0.0),
                        'trade_notional_ratios': _serialize_float_series(sim['notional_ratios'], default=0.0),
                        'parent_id': gi,
                        'product_names': [display_names[idx] for idx in item['selected_idx']],
                    },
                    'metric': metric,
                }
            except Exception as e:
                results[item['orig_index']] = {'index': item['orig_index'], 'success': False, 'error': str(e)}
        else:
            # 多个派生组共享同一基础组 → 批量一次精选组交易簿模拟
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
                        'total_equity': _serialize_float_series(sim['total_equity'], default=0.0),
                        'gross_returns': _serialize_float_series(sim['gross_returns'], default=0.0),
                        'fee_costs': _serialize_float_series(sim['fee_costs'], default=0.0),
                        'trade_notional_ratios': _serialize_float_series(sim['notional_ratios'], default=0.0),
                        'parent_id': gi,
                        'product_names': [display_names[idx] for idx in item['selected_idx']],
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
    其中 fee_map 仅在模式3时非空，key 格式保留 rate/fixed/spec 字段：
    {open_rate, open_fixed, close_rate, close_fixed, close_today_rate,
     close_today_fixed, close_yesterday_rate, close_yesterday_fixed,
     multiplier, min_tick, min_trade_quantity, long_margin_ratio, short_margin_ratio}。
    模式1/2 时 fee_map 为空字典，由调用方用 fee_uniform 的 half_fee 作为 fallback。
    """
    fee_uniform = float(data.get('fee', 0.0) or 0.0) / 100.0
    fee_map_raw = data.get('fee_map', {}) or {}
    use_closetoday = bool(data.get('use_closetoday', False))

    # 模式1/2：不扣除或统一费率 → fee_map 保持空
    if not fee_map_raw:
        return fee_uniform, {}, use_closetoday

    # 模式3：按品种费率 → 前端已传全量 FeeData + 用户覆盖。
    # ratio 与 fixed 分开保存；不要把固定费用折算成“有效费率”。
    fee_map: dict[str, dict[str, float]] = {}
    for code, rates in fee_map_raw.items():
        code_upper = str(code).upper()
        o = float(rates.get('open_ratio', rates.get('open_rate', 0)) or 0)
        c = float(rates.get('close_ratio', rates.get('close_rate', 0)) or 0)
        ct = float(rates.get('closetoday_ratio', rates.get('close_today_rate', 0)) or 0)
        of = float(rates.get('open_fixed', 0) or 0)
        cf = float(rates.get('close_fixed', 0) or 0)
        ctf = float(rates.get('closetoday_fixed', rates.get('close_today_fixed', 0)) or 0)
        fee_map[code_upper] = {
            'open_rate': o,
            'open_fixed': of,
            'close_rate': c,
            'close_fixed': cf,
            'close_today_rate': ct,
            'close_today_fixed': ctf,
            'close_yesterday_rate': c,
            'close_yesterday_fixed': cf,
            'multiplier': float(rates.get('multiplier', 1) or 1),
            'min_tick': float(rates.get('min_tick', 0) or 0),
            'min_trade_quantity': float(rates.get('min_trade_quantity', rates.get('lot_size', 1)) or 1),
            'long_margin_ratio': float(rates.get('long_margin_ratio', 1) or 1),
            'short_margin_ratio': float(rates.get('short_margin_ratio', rates.get('long_margin_ratio', 1)) or 1),
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


def _build_flat_groups_from_payload(
    payload_entry: dict,
    *,
    entry_index: int = 0,
) -> tuple[list, list[dict] | None]:
    """Build a flat list of _FactorGroupTestGroup from a single frontend payload entry.

    Parses the frontend ``groups`` array (flat format) and converts each entry
    into a ``_FactorGroupTestGroup`` instance.

    Returns
    -------
    (groups, ls_configs) where groups is list[_FactorGroupTestGroup] and
    ls_configs is parsed LS configs (or None).
    """
    from tools.factors.tests.group import _FactorGroupTestGroup

    factor_alias = str(payload_entry.get('factor_alias') or '')
    n_groups = int(payload_entry.get('n_groups', 5))
    submission_id = str(payload_entry.get('submission_id') or '')
    groups = payload_entry.get('groups')
    group_names = payload_entry.get('group_names')

    # Parse group names (for base groups without their own name)
    if isinstance(groups, list) and groups:
        n_groups_name, _ = _parse_groups_payload(groups)
    else:
        n_groups_name = _parse_group_names_payload(group_names)
    if not n_groups_name:
        n_groups_name = {i: f"Group {i+1}" for i in range(n_groups)}

    flat_groups: list = []

    if isinstance(groups, list) and groups:
        for item in groups:
            if not isinstance(item, dict):
                continue
            has_parent = bool(item.get('parentId') or item.get('parent_id'))
            if not has_parent:
                # Base group (no parentId): one flat group per entry
                try:
                    gi = int(item.get('group_index', item.get('groupIndex', 0)))
                except (TypeError, ValueError):
                    continue
                display_name = item.get('key') or item.get('shortAlias') or item.get('name') or n_groups_name.get(gi, f'group_{gi}')
                flat_groups.append(_FactorGroupTestGroup(
                    tester_id=submission_id,
                    factor_alias=factor_alias,
                    n_groups=n_groups,
                    group_index=gi,
                    key=str(display_name),
                    name=str(display_name),
                    product_list=None,
                    fee_map=item.get('fee_map') or item.get('feeMap'),
                    fee_mode=item.get('fee_mode') or item.get('feeMode'),
                    fee_rate=item.get('fee_rate', item.get('feeRate')),
                    use_close_today=item.get('use_close_today', item.get('useCloseToday')),
                    rebalance_mode=item.get('rebalance_mode') or item.get('rebalanceMode'),
                    liquidity_mode=item.get('liquidity_mode') or item.get('liquidityMode'),
                    liquidity_percent=item.get('liquidity_percent', item.get('liquidityPercent')),
                    margin_mode=item.get('margin_mode') or item.get('marginMode'),
                ))
            else:
                # Screened group (has parentId): one flat group with product_list
                base_group = int(item.get('baseGroup', item.get('base_group',
                    item.get('parentId', item.get('parent_id', 0)))))
                product_names = _extract_product_names_from_group(item)
                if not product_names:
                    continue
                display_name = item.get('key') or item.get('shortAlias') or item.get('name') or f'筛选_{base_group}'
                flat_groups.append(_FactorGroupTestGroup(
                    tester_id=submission_id,
                    factor_alias=factor_alias,
                    n_groups=n_groups,
                    group_index=base_group,
                    key=str(display_name),
                    name=str(display_name),
                    product_list=product_names,
                    fee_map=item.get('fee_map') or item.get('feeMap'),
                    fee_mode=item.get('fee_mode') or item.get('feeMode'),
                    fee_rate=item.get('fee_rate', item.get('feeRate')),
                    use_close_today=item.get('use_close_today', item.get('useCloseToday')),
                    rebalance_mode=item.get('rebalance_mode') or item.get('rebalanceMode'),
                    liquidity_mode=item.get('liquidity_mode') or item.get('liquidityMode'),
                    liquidity_percent=item.get('liquidity_percent', item.get('liquidityPercent')),
                    margin_mode=item.get('margin_mode') or item.get('marginMode'),
                ))
    else:
        # No groups payload: create default base groups from group_names
        for gi in range(n_groups):
            display_name = n_groups_name.get(gi, f'Group {gi + 1}')
            flat_groups.append(_FactorGroupTestGroup(
                tester_id=submission_id,
                factor_alias=factor_alias,
                n_groups=n_groups,
                group_index=gi,
                key=str(display_name),
                name=str(display_name),
            ))

    # Parse LS configs
    raw_ls = payload_entry.get('ls_configs')
    ls_configs = None
    if isinstance(raw_ls, list) and raw_ls:
        ls_configs = []
        for raw in raw_ls:
            if isinstance(raw, dict):
                parsed = _parse_ls_config({'ls_config': raw}, n_groups)
                if parsed['long'] and parsed['short']:
                    ls_configs.append(parsed)

    return flat_groups, ls_configs


def _serialize_group_simulation_result(
    *,
    tester: Any,
    submission_id: str,
    factor_alias: str,
    n_groups: int,
    ls_configs: list[dict] | None,
    rebalance_mode: str,
    simulation_result: dict[str, Any],
    flat_group_info: list[dict] | None = None,
) -> dict[str, Any]:
    report_df = simulation_result['report_df']
    idx_list = simulation_result['idx_list']
    timestamps = [to_epoch_ms(_signal_time(d)) for d in idx_list]
    group_result = simulation_result['group_result']
    n_total = group_result.returns_np.shape[1] if group_result is not None else n_groups

    # ── Resolve group metadata: prefer flat_group_info, fallback to derived_info ──
    if flat_group_info is not None and len(flat_group_info) > 0:
        # New flat model: every group is a flat entry
        n_base = sum(1 for fi in flat_group_info if not fi.get('product_names'))
        derived_info = [
            fi for fi in flat_group_info
            if fi.get('product_names')
        ]
        # derived_info entries have base_group pointing to the base group index
    else:
        # Old model: fallback
        n_base = getattr(group_result, 'n_base', n_groups) or n_groups
        derived_info = getattr(group_result, 'derived_info', None) or []

    _gross = group_result.gross_returns_np if group_result is not None else None
    gross_np = _gross if _gross is not None else np.zeros((len(timestamps), n_total))
    _fee = group_result.fee_costs_np if group_result is not None else None
    fee_np = _fee if _fee is not None else np.zeros((len(timestamps), n_total))

    # 用模拟中实盘总权益（市值+现金），而非 cumsum(returns)
    _equity = group_result.total_equity_np if group_result is not None else None
    equity_np = _equity if _equity is not None else np.zeros((len(timestamps), n_total))
    # 兜底：总权益为 0 的一律用 initial_capital 填充（首行无数据等边界情况）
    cap = float(getattr(group_result, 'initial_capital', None) or 100000000.0)
    equity_np = np.where(equity_np <= 0, cap, equity_np)
    result_group_names = getattr(group_result, 'group_names', None) or {}
    capital_warning = _build_zero_position_warning(group_result)

    groups_data = []
    _progress(
        f"simulation serialize groups start submission={submission_id} "
        f"factor={factor_alias} total_groups={n_total}"
    )
    for g in range(n_total):
        _progress(
            f"simulation serialize group {g + 1}/{n_total} "
            f"submission={submission_id} factor={factor_alias}"
        )
        is_child = g >= n_base
        vals = [round(float(v), 2) if not (math.isnan(v) or math.isinf(v)) else None for v in equity_np[:, g]]
        gross_vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else 0.0 for v in gross_np[:, g]]
        fee_vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else 0.0 for v in fee_np[:, g]]
        group_key = _group_display_key(g, n_base, derived_info, result_group_names)
        if is_child:
            di = derived_info[g - n_base]
            group_name = di.get('name', f'Group {g + 1}')
        else:
            group_name = group_key
        entry = {
            'key': group_key,
            'name': group_name,
            'group_index': g,
            'submission_id': submission_id,
            'timestamps': timestamps,
            'total_equity': vals,
            'gross_returns': gross_vals,
            'fee_costs': fee_vals,
            'trade_notional_ratios': [
                round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else 0.0
                for v in group_result.trade_notional_ratio_np[:, g]
            ] if group_result is not None and group_result.trade_notional_ratio_np is not None else [],
        }
        if is_child:
            di = derived_info[g - n_base]
            entry['parent_id'] = di['base_group']
            entry['product_names'] = di['product_names']
            if di.get('id'):
                entry['_id'] = di['id']
        groups_data.append(entry)
    _progress(f"simulation serialize groups done submission={submission_id} factor={factor_alias}")

    metrics: dict = {}
    if not report_df.empty:
        raw_metrics = report_df.to_dict(orient='index')
        for metric_idx, (k, v) in enumerate(raw_metrics.items(), start=1):
            _progress(
                f"simulation serialize metric {metric_idx}/{len(raw_metrics)} "
                f"submission={submission_id} factor={factor_alias}"
            )
            display_key = _metric_display_key(k, n_base, derived_info, result_group_names)
            metrics[display_key] = {
                mk: (None if mv is None or (isinstance(mv, float) and (math.isnan(mv) or math.isinf(mv))) else float(mv))
                for mk, mv in v.items()
            }
    used_keys = set(metrics.keys())
    if ls_configs:
        for ls_idx, ls_config in enumerate(ls_configs, start=1):
            _progress(
                f"simulation LS start {ls_idx}/{len(ls_configs)} "
                f"submission={submission_id} factor={factor_alias} name={ls_config.get('name')}"
            )
            r_ls, ls_cum_arr = _compute_weighted_ls_returns(gross_np, fee_np, ls_config, n_total)
            ls_name = ls_config['name'] or 'Long-Short'
            ls_key = _unique_group_key(ls_name, used_keys)
            ls_vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else None for v in ls_cum_arr]
            groups_data.append({
                'key': ls_key,
                'name': ls_name,
                'submission_id': submission_id,
                'timestamps': timestamps,
                'total_equity': ls_vals,
                'gross_returns': _serialize_float_series(r_ls, default=0.0),
                'fee_costs': [0.0] * len(r_ls),
                'trade_notional_ratios': [0.0] * len(r_ls),
                'is_ls': True,
                'ls_info': {'type': 'long_short', 'key': ls_key, 'config': ls_config},
            })
            metrics[ls_key] = _compute_ls_metrics(r_ls, report_df, idx_list)
            _progress(
                f"simulation LS done {ls_idx}/{len(ls_configs)} "
                f"submission={submission_id} factor={factor_alias} key={ls_key}"
            )

    return {
        'success': True,
        'groups': groups_data,
        'metrics': metrics,
        'n_groups': n_total,
        'n_base': n_base,
        'initial_capital': float(group_result.initial_capital) if group_result is not None and getattr(group_result, 'initial_capital', None) is not None else None,
        'multi_session_active': bool(group_result.multi_session_active) if group_result is not None else False,
        'capital_warning': capital_warning,
        'rebalance_mode': rebalance_mode,
        'submission_id': submission_id,
        'factor_alias': factor_alias,
        'tester_alias': getattr(tester, 'alias', '?'),
        'tester_product_count': len(tester.products) if hasattr(tester, 'products') else 0,
        '_raw': {
            'gross_np': gross_np,
            'fee_np': fee_np,
            'timestamps': timestamps,
            'report_df': report_df,
            'idx_list': idx_list,
        },
    }


@sft_bp.route('/run_group_test', methods=['POST'])
def run_group_test():
    """批量并行运行多个分组测试提交条目，支持跨提交条目的 Long-Short。
    
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
        "rebalance_mode": "buy_and_hold",
        "derived_groups": null
    }
    
    请求里的 `batches` / `cross_batch_ls` 仍保留原字段名；
    后端内部按 submission entry / cross-entry LS 处理。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    data = request.get_json()
    submitted_entries = data.get('batches')
    if not isinstance(submitted_entries, list) or not submitted_entries:
        return jsonify({'success': False, 'error': 'batches 必须是非空数组'}), 400

    request_started = time.perf_counter()
    cross_entry_ls_requests = data.get('cross_batch_ls') or []
    _progress(
        f"group simulations request start entries={len(submitted_entries)} "
        f"cross_entry_ls={len(cross_entry_ls_requests) if isinstance(cross_entry_ls_requests, list) else 0}"
    )

    rebalance_mode = str(data.get('rebalance_mode', 'buy_and_hold') or 'buy_and_hold')

    from tools.data.DataTime import DataTime

    # 精度统一：start/end 同精度
    precision = data.get("precision") or data.get("time_precision") or "exact"
    start_dt = DataTime.from_dict(data, precision=precision)
    end_data = dict(data)
    # 将 start_xxx 映射为 end_xxx，from_dict 会取第一个有值的
    end_data["date"] = end_data.pop("end_date", end_data.pop("date", None))
    end_data["time"] = end_data.pop("end_time", end_data.pop("time", None))
    end_dt = DataTime.from_dict(end_data, precision=precision)

    try:
        initial_capital = _parse_initial_capital(data.get('initial_capital'))
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    derived_groups = data.get('derived_groups', None)
    # 费率从第一个前端提交条目的 tester 解析
    first_entry = submitted_entries[0]
    try:
        sub_id = first_entry.get('submission_id')
        tester0 = runtime_state.get_factor_tester(sub_id, caller='run_group_test')
        fee_uniform, fee_map, use_closetoday = _parse_group_fee_config(data, getattr(tester0, 'products', None))
    except Exception as e:
        return jsonify({'success': False, 'error': f'费率解析失败: {e}'}), 400

    from tools.factors.tests.group import _FactorGroupTestGroup

    # ── Build flat groups from all submitted entries ──
    all_flat_groups: list[_FactorGroupTestGroup] = []
    sim_index_by_group: dict[int, int] = {}  # flat_group_position → simulation_index
    all_ls_configs_by_index: dict[int, list[dict] | None] = {}
    # Also collect factor_aliases per submission for calendar building
    factor_aliases_by_submission: dict[str, list[str]] = {}

    for idx, payload_entry in enumerate(submitted_entries):
        if not isinstance(payload_entry, dict):
            continue
        submission_id = str(payload_entry.get('submission_id') or '')
        flat_groups, ls_configs = _build_flat_groups_from_payload(
            payload_entry, entry_index=idx,
        )
        offset = len(all_flat_groups)
        for gi, _ in enumerate(flat_groups):
            sim_index_by_group[offset + gi] = idx
        all_flat_groups.extend(flat_groups)
        all_ls_configs_by_index[idx] = ls_configs
        factor_alias = str(payload_entry.get('factor_alias') or '')
        if factor_alias:
            factor_aliases_by_submission.setdefault(submission_id, [])
            if factor_alias not in factor_aliases_by_submission[submission_id]:
                factor_aliases_by_submission[submission_id].append(factor_alias)

    if not all_flat_groups:
        return jsonify({'success': False, 'error': '没有有效的分组配置'}), 400

    auto_group_calendar_freq = bool(data.get('auto_group_calendar_freq', True))
    requested_group_calendar_freq = None if auto_group_calendar_freq else data.get('group_calendar_freq')
    _progress(
        f"calendar resolve start submissions={len(factor_aliases_by_submission)} "
        f"mode={'auto' if auto_group_calendar_freq else 'manual'} "
        f"requested={requested_group_calendar_freq if requested_group_calendar_freq is not None else 'auto'}"
    )

    # 构建跨所有 tester 的统一 calendar_index。
    calendar_indices: list[pd.Index] = []
    all_factor_freqs: list[Any] = []
    for submission_id, factor_aliases in factor_aliases_by_submission.items():
        try:
            tester = runtime_state.get_factor_tester(submission_id, caller='run_group_test_calendar')
        except Exception as exc:
            _progress(f"calendar build skip submission={submission_id} error={exc}")
            continue
        tester_factor_freqs = tester.collect_group_factor_freqs(factor_aliases)
        all_factor_freqs.extend(tester_factor_freqs)
        _progress(
            f"calendar factors submission={submission_id} "
            f"factors={len(factor_aliases)} factor_freqs={[str(freq) for freq in tester_factor_freqs]}"
        )
    try:
        effective_group_calendar_freq = FactorTester.resolve_group_calendar_freq_from_factor_freqs(
            all_factor_freqs,
            'auto' if auto_group_calendar_freq else requested_group_calendar_freq,
        )
    except ValueError as exc:
        return jsonify({
            'success': False,
            'error': str(exc),
        }), 400
    _progress(
        f"calendar resolve done effective_freq={effective_group_calendar_freq} "
        f"factor_freq_count={len(all_factor_freqs)}"
    )
    for submission_id, factor_aliases in factor_aliases_by_submission.items():
        tester = runtime_state.get_factor_tester(submission_id, caller='run_group_test_calendar_build')
        _progress(
            f"calendar build start submission={submission_id} "
            f"factors={len(factor_aliases)} freq={effective_group_calendar_freq}"
        )
        tester_calendar = tester.build_group_calendar_index(
            factor_aliases,
            requested_calendar_freq=effective_group_calendar_freq,
        )
        if len(tester_calendar) > 0:
            calendar_indices.append(tester_calendar)
            _progress(
                f"calendar build submission={submission_id} "
                f"points={len(tester_calendar)} factors={len(factor_aliases)} "
                f"freq={effective_group_calendar_freq}"
            )
        else:
            _progress(
                f"calendar build submission={submission_id} empty "
                f"factors={len(factor_aliases)} freq={effective_group_calendar_freq}"
            )
    global_calendar_index = tester0.merge_group_calendar_indices(calendar_indices)
    if len(global_calendar_index) > 0:
        _progress(
            f"calendar build global points={len(global_calendar_index)} "
            f"submissions={len(calendar_indices)} freq={effective_group_calendar_freq} "
            f"mode={'auto' if auto_group_calendar_freq else 'manual'}"
        )
    else:
        _progress(
            f"calendar build global empty submissions={len(calendar_indices)} "
            f"freq={effective_group_calendar_freq}"
        )

    # 构建前端提交条目→索引映射（供 cross-entry LS 反查）
    entry_index_by_key: dict[str, int] = {}
    for i, payload_entry in enumerate(submitted_entries):
        key = f"{payload_entry.get('submission_id','')}|{payload_entry.get('factor_alias','')}|{int(payload_entry.get('n_groups', 5))}"
        entry_index_by_key[key] = i

    submission_results: list[dict | None] = [None] * len(submitted_entries)
    errors = []
    from tools.factors.tests.single_factor_test.group.group_tester import FactorGroupTester

    overlap_ratio = float(data.get('group_overlap_ratio', 0.35) or 0.35)
    containment_ratio = float(data.get('group_containment_ratio', 0.60) or 0.60)
    merge_cost_ratio = float(data.get('group_merge_cost_ratio', 1.15) or 1.15)
    group_tester = FactorGroupTester.from_flat_groups(
        all_flat_groups,
        spec_index_by_group=sim_index_by_group,
        ls_configs_by_index=all_ls_configs_by_index,
        start_dt=start_dt,
        end_dt=end_dt,
        calendar_index=global_calendar_index if len(global_calendar_index) > 0 else None,
        rebalance_mode=rebalance_mode,
        overlap_ratio=overlap_ratio,
        containment_ratio=containment_ratio,
        merge_cost_ratio=merge_cost_ratio,
        progress_hook=_progress,
    )
    _progress(
        f"group tester batches overlap_ratio={overlap_ratio:.2f} "
        f"containment_ratio={containment_ratio:.2f} merge_cost_ratio={merge_cost_ratio:.2f} "
        f"batches={group_tester.build_batch_labels()}"
    )
    try:
        raw_results = group_tester.run(
            fee=fee_uniform,
            fee_map=fee_map,
            use_closetoday=use_closetoday,
            initial_capital=initial_capital,
            rebalance_mode=rebalance_mode,
            start_dt=start_dt,
            end_dt=end_dt,
            calendar_index=global_calendar_index if len(global_calendar_index) > 0 else None,
            progress_hook=_progress,
        )
    except Exception as e:
        errors.append({'error': str(e)})
        raw_results = []

    for raw_result in raw_results:
        idx = int(raw_result.get('simulation_index', -1))
        if idx < 0 or idx >= len(submitted_entries):
            continue
        payload_entry = submitted_entries[idx]
        # Collect flat_group_info for this simulation_index
        si_groups = [
            g for gi, g in enumerate(all_flat_groups)
            if sim_index_by_group.get(gi) == idx
        ]
        # Build flat_group_info list matching the group order in the result
        flat_info = [
            {
                'base_group': g.group_index,
                'key': g.key,
                'name': g.name,
                'id': g._id,
                'product_names': g.product_list,
                'fee_mode': g.fee_mode,
                'fee_rate': g.fee_rate,
                'fee_map': g.fee_map,
                'use_close_today': g.use_close_today,
                'rebalance_mode': g.rebalance_mode,
                'liquidity_mode': g.liquidity_mode,
                'liquidity_percent': g.liquidity_percent,
                'margin_mode': g.margin_mode,
            }
            for g in si_groups
        ]
        serialized = _serialize_group_simulation_result(
            tester=raw_result['tester'],
            submission_id=str(raw_result.get('submission_id') or ''),
            factor_alias=str(raw_result.get('factor_alias') or ''),
            n_groups=int(raw_result.get('n_groups', 5)),
            ls_configs=raw_result.get('ls_configs'),
            rebalance_mode=str(payload_entry.get('rebalance_mode') or rebalance_mode),
            simulation_result=raw_result,
            flat_group_info=flat_info if flat_info else None,
        )
        serialized['submission_id'] = str(raw_result.get('submission_id') or '')
        serialized['factor_alias'] = str(raw_result.get('factor_alias') or '')
        serialized['n_groups_requested'] = int(raw_result.get('n_groups', 5))
        serialized['simulation_index'] = idx
        submission_results[idx] = serialized
        _progress(f"group tester accepted index={idx + 1}/{len(submitted_entries)}")

    valid_results = [r for r in submission_results if r is not None]
    _progress(f"submission parallel done valid={len(valid_results)} errors={len(errors)}")
    if not valid_results:
        first_err = errors[0] if errors else {'error': '所有提交条目均失败'}
        return jsonify({
            'success': False,
            'error': first_err.get('error', '所有提交条目均失败'),
            'traceback': first_err.get('traceback'),
            'simulation_errors': errors,
        }), 500

    # ── 阶段 2：跨 tester LS 计算 ──
    def _find_raw(br_dict: dict | None) -> dict | None:
        return br_dict.get('_raw') if br_dict else None

    cross_ls_groups: list[dict] = []
    cross_ls_metrics: dict = {}

    if cross_entry_ls_requests:
        _progress(f"cross-entry LS start count={len(cross_entry_ls_requests)}")
        for cb_idx, cb in enumerate(cross_entry_ls_requests, start=1):
            if not isinstance(cb, dict):
                _progress(f"cross-entry LS skip {cb_idx}/{len(cross_entry_ls_requests)} invalid config")
                continue
            long_info: dict = cb.get('long') or {}
            short_info: dict = cb.get('short') or {}
            ls_name = str(cb.get('name') or 'Long-Short').strip() or 'Long-Short'
            _progress(f"cross-entry LS compute {cb_idx}/{len(cross_entry_ls_requests)} name={ls_name}")

            long_n_groups = int(long_info.get('n_groups', long_info.get('group_count', 5)) or 5)
            short_n_groups = int(short_info.get('n_groups', short_info.get('group_count', 5)) or 5)
            long_key = f"{long_info.get('submission_id','')}|{long_info.get('factor_alias','')}|{long_n_groups}"
            short_key = f"{short_info.get('submission_id','')}|{short_info.get('factor_alias','')}|{short_n_groups}"
            long_entry_idx = entry_index_by_key.get(long_key)
            short_entry_idx = entry_index_by_key.get(short_key)

            if long_entry_idx is None or short_entry_idx is None:
                _progress(f"cross-entry LS skip {cb_idx}/{len(cross_entry_ls_requests)} missing source entry")
                continue

            long_br = submission_results[long_entry_idx]
            short_br = submission_results[short_entry_idx]
            if long_br is None or short_br is None:
                _progress(f"cross-entry LS skip {cb_idx}/{len(cross_entry_ls_requests)} failed source entry")
                continue
            long_raw = _find_raw(long_br)
            short_raw = _find_raw(short_br)
            if long_raw is None or short_raw is None:
                _progress(f"cross-entry LS skip {cb_idx}/{len(cross_entry_ls_requests)} missing raw arrays")
                continue

            long_group = int(long_info.get('group', 0))
            short_group = int(short_info.get('group', 0))
            long_n = long_br.get('n_groups_requested', 5)
            short_n = short_br.get('n_groups_requested', 5)

            # 跨提交条目 LS：从不同 simulation entry 的 gross_np / fee_np 拼成 (T, 2) 数组
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

            # 用第一个 source entry 的 report_df 和 idx_list 来计算 metrics（近似）
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
                'total_equity': ls_vals,
                'gross_returns': _serialize_float_series(r_ls, default=0.0),
                'fee_costs': [0.0] * len(r_ls),
                'trade_notional_ratios': [0.0] * len(r_ls),
                'is_ls': True,
                'is_cross_batch': True,
                'cross_ls_info': {
                    'type': 'long_short',
                    'long_batch': long_info,
                    'short_batch': short_info,
                },
            })
            cross_ls_metrics[ls_key] = _compute_ls_metrics(r_ls, ref_report, ref_idx)
            _progress(f"cross-entry LS done {cb_idx}/{len(cross_entry_ls_requests)} name={ls_name}")

    # ── 阶段 3：合并结果 ──
    _progress(
        f"simulation merge start valid={len(valid_results)} "
        f"cross_ls={len(cross_ls_groups)}"
    )
    merged_groups = []
    merged_metrics = {}
    used_merged_keys: set[str] = set()
    multi_session_entries = []
    last_n_groups = 0
    last_multi_session = False
    last_rebalance = rebalance_mode

    for br_idx, br in enumerate(valid_results, start=1):
        _progress(
            f"simulation merge result {br_idx}/{len(valid_results)} "
            f"submission={br.get('submission_id')} factor={br.get('factor_alias')}"
        )
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
        simulation_multi_session = bool(br.get('multi_session_active', False))
        if simulation_multi_session:
            multi_session_entries.append({
                'index': br.get('simulation_index'),
                'submission_id': br.get('submission_id'),
                'factor_alias': br.get('factor_alias'),
                'tester_alias': br.get('tester_alias'),
                'n_groups': br.get('n_groups_requested') or br.get('n_groups'),
            })
        last_multi_session = simulation_multi_session or last_multi_session
        last_rebalance = br.get('rebalance_mode', last_rebalance) or last_rebalance

    # 追加跨提交条目 LS 组
    if cross_ls_groups:
        for group_idx, group in enumerate(cross_ls_groups, start=1):
            _progress(f"simulation merge cross LS group {group_idx}/{len(cross_ls_groups)}")
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

    _progress(
        f"group simulations request done groups={len(merged_groups)} metrics={len(merged_metrics)} "
        f"elapsed={time.perf_counter() - request_started:.2f}s"
    )
    return jsonify({
        'success': True,
        'groups': merged_groups,
        'metrics': merged_metrics,
        'n_groups': last_n_groups,
        'multi_session_active': last_multi_session,
        'multi_session_entries': multi_session_entries,
        'rebalance_mode': last_rebalance,
        'submission_id': submitted_entries[0].get('submission_id', ''),
        'factor_alias': submitted_entries[0].get('factor_alias', ''),
        'tester_alias': valid_results[0].get('tester_alias', '?') if valid_results else '?',
        'tester_product_count': valid_results[0].get('tester_product_count', 0) if valid_results else 0,
        'simulation_count': len(valid_results),
        'cross_batch_ls_count': len(cross_ls_groups),
        'errors': errors if errors else None,
    })

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
        products_dict = group_result.get_products_by_group() if group_result is not None else None
        valid_cols_raw = group_result.valid_cols if group_result is not None else None
        if not products_dict or not _safe_bool(valid_cols_raw):
            return jsonify({'success': False, 'error': '未找到最近的分组测试结果，请先运行分组测试'}), 400
        valid_cols = valid_cols_raw

        # 找到最接近的时刻
        # products_dict: {group_idx: {index_entry: [product_names]}}
        # index_entry 可能是 Timestamp 或 tuple
        first_group = next(iter(products_dict.values()))
        time_entries = list(first_group.keys())
        if not time_entries:
            return jsonify({'success': False, 'error': '未找到匹配的时间点'}), 404

        def _epoch_seconds(value):
            ts = _signal_time(value)
            if isinstance(ts, pd.Timestamp):
                ts_no_tz_untyped = ts.tz_localize(None) if ts.tzinfo else ts
                return float(pd.Timestamp(ts_no_tz_untyped).value // 10**9)
            if hasattr(ts, 'timestamp'):
                return float(pd.Timestamp(ts).value // 10**9)
            return float(ts)

        time_epochs = np.array([_epoch_seconds(idx_entry) for idx_entry in time_entries], dtype=float)

        # 前端传来的 UTC epoch 毫秒
        target_epoch = float(timestamp_ms) / 1000.0

        # 找最近的
        best_pos = int(np.argmin(np.abs(time_epochs - target_epoch)))
        best_idx_entry = time_entries[best_pos]

        # 找到上一时刻 — 用 all_times 的 epoch 排序（避免 tuple/array 直接比较）
        # 用 enumerate 添加位置索引作为 tiebreaker，防止 sorted 回退到 tuple 比较
        # （idx_entry 可能为包含 numpy 类型的 tuple，其 __eq__ 会触发 ambiguous truth value）
        sorted_pos = np.argsort(time_epochs, kind='stable')
        current_pos = int(np.flatnonzero(sorted_pos == best_pos)[0]) if sorted_pos.size else 0
        prev_entry = time_entries[int(sorted_pos[current_pos - 1])] if current_pos > 0 else None

        # (ts_epoch, idx_entry) 对列表，供 all_timestamps_ms 构建和前/后导航使用
        all_times = list(zip(time_epochs, time_entries))

        n_groups = len(products_dict)
        fee_rates_by_name = _product_fee_rates_by_name(group_result)

        # ── 持仓金额数据 (refs #100) ──
        hold_np = getattr(group_result, 'hold_amounts_np', None)
        t_idx = None
        assert group_result is not None, "group_result should not be None here"
        if hold_np is not None and group_result.index_list:
            try:
                t_idx = group_result.index_list.index(best_idx_entry)
            except (ValueError, AttributeError):
                t_idx = None

        # 构建 valid_cols → position 映射（hold_np 的 P 轴与 valid_cols 对齐）
        valid_cols_list = group_result.valid_cols if group_result.valid_cols else []
        col_to_pos = {col: i for i, col in enumerate(valid_cols_list)} if valid_cols_list else {}

        groups_detail = []
        for g in range(n_groups):
            current_raw = products_dict[g].get(best_idx_entry, [])
            current_display = [_display_product_with_fee(x, fee_rates_by_name) for x in current_raw]
            # 按 name 排序
            current_display.sort(key=lambda d: d['name'])

            # ── 注入持仓金额 (refs #100) ──
            g_amounts = None
            if t_idx is not None and hold_np is not None and hold_np.shape[0] > t_idx:
                # hold_np shape: (T, M, P)；M 可能 > n_groups（variant 扩展）
                # 当 M > n_groups 时，产品金额可能分布在同一 base group 的多个 variant 中
                # products_dict 的 key 是 base group index
                # 简化处理：取 g 对应的 variant 金额；若 M == n_groups，直接用 g
                if g < hold_np.shape[1]:
                    g_amounts = hold_np[t_idx, g, :]  # (P,) — 该组每产品持仓金额
                elif hasattr(group_result, 'n_base') and group_result.n_base is not None:
                    # 存在 variant 扩展：暂不处理（require further design）
                    pass
                else:
                    # fallback: 取 g 但可能 index error
                    pass

            total_amount = float(np.nansum(g_amounts)) if g_amounts is not None and current_raw else 0.0

            # 注入 amount/weight/pending_exit 到每个产品
            if g_amounts is not None and col_to_pos and total_amount > 0:
                for d in current_display:
                    pname = d.get('name', '')
                    pos = col_to_pos.get(pname)
                    if pos is not None and pos < len(g_amounts):
                        amt = float(g_amounts[pos])
                        d['amount'] = round(amt, 6)
                        d['weight'] = round(amt / total_amount, 6) if total_amount > 0 else 0.0
                        # pending_exit: 在 membership 中但 amount ≈ 0（低于组资产的万分之一）
                        d['pending_exit'] = amt < total_amount * 0.0001
            elif current_raw:
                # 无金额数据时，amount 留空
                for d in current_display:
                    d['amount'] = None
                    d['weight'] = None
                    d['pending_exit'] = False

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

        # ── 附加元信息供前端按 shortAlias 分层渲染 (refs #100) ──
        snapshot_n_base = getattr(group_result, 'n_base', n_groups) or n_groups
        snapshot_n_derived = getattr(group_result, 'n_derived', 0) or 0
        snapshot_derived_info = getattr(group_result, 'derived_info', None) or []
        _raw_group_names = getattr(group_result, 'group_names', None) or {}
        snapshot_group_names = {}
        for k, v in _raw_group_names.items():
            try:
                snapshot_group_names[int(k)] = str(v)
            except (TypeError, ValueError):
                snapshot_group_names[str(k)] = str(v)

        return jsonify({
            'success': True,
            'groups': groups_detail,
            'timestamp_ms': closest_ms,
            'has_prev': prev_entry is not None,
            'has_next': current_index >= 0 and current_index < len(all_timestamps_ms) - 1,
            'all_timestamps_ms': all_timestamps_ms,
            'n_base': snapshot_n_base,
            'n_derived': snapshot_n_derived,
            'derived_info': snapshot_derived_info,
            'group_names': snapshot_group_names,
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
        products = group_result.get_products_by_group() if group_result is not None else None
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
    """批量生成多个派生组（一次调用，后端一次交易簿模拟计算同基础组的所有派生组）。"""
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
        # 从请求中解析费率
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
