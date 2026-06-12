"""Group test endpoint."""
import logging, math, time, traceback
from typing import Any, cast
import numpy as np
import pandas as pd
from flask import request, jsonify
from tools.factors.FactorTester import FactorTester, _active_tester, _signal_time
from tools.factors.Parameters import FactorNextPeriodReturns
from tools.factors.tests.single_factor_test.group.core import infer_periods_per_year
from tools.factors.tests.single_factor_test.group.core import _emit_progress as _core_emit_progress
from tools.factors.tests.single_factor_test.group.core import ensure_group_factor_inputs
from tools.factors.tests.single_factor_test.group.detail import build_group_detail
from tools.factors.tests.single_factor_test.group.metadata import GROUP_TEST_PHASES, GROUP_TEST_METRICS_META
from tools.factors.tests.single_factor_test.group.monotonicity import build_group_ranking_detail
from . import sft_bp
import server.services.runtime_state as runtime_state
from server.modules.shared.price_data_helpers import to_epoch_ms
from server.services.factor_registry import get_factor_family_instance

_log = logging.getLogger(__name__)


def _ensure_tester_factors_for_group(
    tester: Any,
    factor_aliases: list[str],
    factor_family_alias: str | None,
    *,
    params_list: list | None = None,
    username: str | None = None,
) -> None:
    """Ensure direct group runs can resolve factors even when IC has not run."""
    missing_aliases = [
        str(alias) for alias in factor_aliases
        if alias and tester.resolve_factor(str(alias)) is None
    ]
    if not missing_aliases:
        return
    if not factor_family_alias:
        return

    factor_family = get_factor_family_instance(str(factor_family_alias), username=username)
    if params_list is None:
        params_list = runtime_state.get_session_params(str(factor_family_alias), factor_family)
    factors = factor_family.get_factors(params_list=params_list)
    existing_by_alias = {getattr(f, 'alias', ''): i for i, f in enumerate(getattr(tester, 'factors', []))}
    for factor in factors:
        alias = getattr(factor, 'alias', '')
        if not alias:
            continue
        if alias in existing_by_alias:
            tester.factors[existing_by_alias[alias]] = factor
        else:
            tester.factors.append(factor)
            existing_by_alias[alias] = len(tester.factors) - 1


def _progress(message: str) -> None:
    print(f"[GroupTest] {message}", flush=True)


def _get_metrics_meta() -> dict:
    """Return the single-source metrics metadata for frontend rendering."""
    return GROUP_TEST_METRICS_META


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


def _group_display_key(group_idx: int, group_names=None) -> str:
    """扁平模型：直接用 group_names dict 或索引作为显示名。"""
    names = _normalize_group_names(group_names)
    if group_idx in names:
        return names[group_idx]
    return str(group_idx)


def _metric_display_key(raw_key, group_names=None) -> str:
    try:
        key_int = int(raw_key)
    except (TypeError, ValueError):
        return str(raw_key)
    return _group_display_key(key_int, group_names)


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

    # ── Resolve group metadata: flat model (all groups are flat entries) ──
    result_group_names = getattr(group_result, 'group_names', None) or {}

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
    capital_warning = _build_zero_position_warning(group_result)

    # Build flat_group_info lookup: {group_index: info_dict}
    flat_info_by_idx: dict[int, dict] = {}
    if flat_group_info:
        for fi in flat_group_info:
            gi = fi.get('group_index', -1)
            if gi >= 0:
                flat_info_by_idx[gi] = fi

    groups_data = []
    _progress(
        f"simulation serialize groups start submission={submission_id} "
        f"factor={factor_alias} total_groups={n_total}"
    )
    _core_emit_progress("serialize", f"开始序列化分组结果，共 {n_total} 组",
                        completed=0, total=n_total)
    for g in range(n_total):
        _progress(
            f"simulation serialize group {g + 1}/{n_total} "
            f"submission={submission_id} factor={factor_alias}"
        )
        _core_emit_progress("serialize", f"序列化分组 {g+1}/{n_total}",
                            completed=g + 1, total=n_total)
        vals = [round(float(v), 2) if not (math.isnan(v) or math.isinf(v)) else None for v in equity_np[:, g]]
        gross_vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else 0.0 for v in gross_np[:, g]]
        fee_vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else 0.0 for v in fee_np[:, g]]
        group_key = _group_display_key(g, result_group_names)
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
        # If this group has a product-level filter (screened subgroup), attach metadata
        fi = flat_info_by_idx.get(g)
        if fi and fi.get('product_names'):
            entry['product_names'] = fi['product_names']
            if fi.get('id'):
                entry['_id'] = fi['id']
        groups_data.append(entry)
    _progress(f"simulation serialize groups done submission={submission_id} factor={factor_alias}")
    _core_emit_progress("serialize", f"分组结果序列化完成，共 {n_total} 组",
                        completed=n_total, total=n_total)

    metrics: dict = {}
    if not report_df.empty:
        raw_metrics = report_df.to_dict(orient='index')
        for metric_idx, (k, v) in enumerate(raw_metrics.items(), start=1):
            _progress(
                f"simulation serialize metric {metric_idx}/{len(raw_metrics)} "
                f"submission={submission_id} factor={factor_alias}"
            )
            display_key = _metric_display_key(k, result_group_names)
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
        'metrics_meta': _get_metrics_meta(),
        'n_groups': n_total,
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
    """运行分组测试，接收扁平 groups + ls_configs + page_uuid。
    
    Request JSON:
    {
        "groups": [ {... group fields (name, groupIndex, factorAlias, testerId, feeMode, ...} ],
        "ls_configs": [ {"name": "LS-1", "long": [...], "short": [...]}, ... ],
        "page_uuid": "...",
        "start_date": "2024-01-01", "end_date": "2024-12-31",
        "initial_capital": 1000000,
    }
    
    前端只传 groups + ls_configs + page_uuid。
    factor_family_alias 从 page_uuid 对应的 page state 解析。
    fee / rebalance / close-today 从 group 自身字段读取。
    跨 tester LS 自动由 ls_configs legs 中不同 tester_id 的合并（build_overlap_batches）处理。
    """
    data = request.get_json(silent=True) or {}
    success, result = _run_group_test_core(data)
    if success:
        return jsonify(result)
    else:
        status = result.get('status', 500)
        return jsonify(result), status


def _run_group_test_core(data: dict) -> tuple[bool, dict]:
    """
    核心分组测试逻辑，可以被 /run_group_test (JSON) 和 /run_group_test_stream (SSE) 共享。
    
    返回 (success, dict)
    - success=True：dict 是成功响应
    - success=False：dict 包含 error 和 status 字段
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from tools.factors.tests.single_factor_test.group import _FactorGroupTestGroup
    from tools.factors.tests.single_factor_test.group.group_tester import FactorGroupTester

    flat_groups_raw = data.get('groups')
    if not isinstance(flat_groups_raw, list) or not flat_groups_raw:
        return False, {'success': False, 'error': 'groups 必须是非空数组', 'status': 400}
    flat_ls_configs = data.get('ls_configs') or []
    if not isinstance(flat_ls_configs, list):
        flat_ls_configs = []

    request_started = time.perf_counter()
    _progress(
        f"group simulations request start groups={len(flat_groups_raw)} "
        f"ls_configs={len(flat_ls_configs)}"
    )

    rebalance_mode = 'buy_and_hold'

    from tools.data.DataTime import DataTime

    precision = data.get("precision") or data.get("time_precision") or "exact"
    start_dt = DataTime.from_dict(data, precision=precision)
    end_data = dict(data)
    end_data["date"] = end_data.pop("end_date", end_data.pop("date", None))
    end_data["time"] = end_data.pop("end_time", end_data.pop("time", None))
    end_dt = DataTime.from_dict(end_data, precision=precision)

    try:
        initial_capital = _parse_initial_capital(data.get('initial_capital'))
    except ValueError as e:
        return False, {'success': False, 'error': str(e), 'status': 400}

    # ── Build _FactorGroupTestGroup from flat groups array ──
    # Group by tester_id, then by factor_alias
    tester_groups: dict[str, dict[str, list[dict]]] = {}  # tester_id → factor_alias → [group_dicts]
    for g in flat_groups_raw:
        if not isinstance(g, dict):
            continue
        tid = str(g.get('testerId') or g.get('tester_id') or '')
        fa = str(g.get('factorAlias') or g.get('factor_alias') or '')
        if not tid or not fa:
            continue
        tester_groups.setdefault(tid, {}).setdefault(fa, []).append(g)

    # Determine n_groups per (tester_id, factor_alias) from max groupIndex
    n_groups_by_triple: dict[tuple, int] = {}
    for tid, by_fa in tester_groups.items():
        for fa, gs in by_fa.items():
            max_idx = 0
            for g in gs:
                gi = int(g.get('groupIndex', g.get('group_index', 0)))
                max_idx = max(max_idx, gi)
            n_groups_by_triple[(tid, fa)] = max(max_idx, len(gs))

    # Build flat _FactorGroupTestGroup list
    all_flat_groups: list[_FactorGroupTestGroup] = []
    sim_index_by_group: dict[int, int] = {}
    all_ls_configs_by_index: dict[int, list[dict] | None] = {}
    factor_aliases_by_submission: dict[str, list[str]] = {}

    sim_index = 0
    for tid, by_fa in tester_groups.items():
        for fa, gs in by_fa.items():
            n_groups = n_groups_by_triple[(tid, fa)]
            existing = factor_aliases_by_submission.get(tid) or []
            if fa not in existing:
                existing.append(fa)
            factor_aliases_by_submission[tid] = existing
            for g in gs:
                gi = int(g.get('groupIndex', g.get('group_index', 0)))
                name = str(g.get('name') or g.get('key') or f'{fa}_G{gi}')
                fg = _FactorGroupTestGroup(
                    tester_id=tid,
                    factor_alias=fa,
                    n_groups=n_groups,
                    group_index=gi,
                    key=name,
                    name=name,
                    product_list=g.get('productMask') or g.get('productList') or None,
                    fee_mode=g.get('feeMode') or g.get('fee_mode') or None,
                    fee_rate=g.get('feeRate') or g.get('fee_rate') or None,
                    fee_modifications=g.get('feeModifications') or g.get('fee_modifications') or None,
                    use_close_today=bool(g.get('useCloseToday') or g.get('use_closetoday')),
                    rebalance_mode=g.get('rebalanceMode') or g.get('rebalance_mode') or None,
                    liquidity_mode=g.get('liquidityMode') or g.get('liquidity_mode') or None,
                    liquidity_percent=g.get('liquidityPercent') or g.get('liquidity_percent') or None,
                    margin_mode=g.get('marginMode') or g.get('margin_mode') or None,
                )
                offset = len(all_flat_groups)
                sim_index_by_group[offset] = sim_index
                all_flat_groups.append(fg)
            all_ls_configs_by_index[sim_index] = flat_ls_configs if flat_ls_configs else None  # all LS configs visible to this spec
            sim_index += 1

    if not all_flat_groups:
        return False, {'success': False, 'error': '没有有效的分组配置', 'status': 400}

    # ── Resolve factor_family_alias from page_uuid ──
    page_uuid = str(data.get('page_uuid') or '')
    factor_family_alias = ''
    if page_uuid:
        try:
            page_state = runtime_state.get_page_state(page_uuid)
            factor_family_alias = str(getattr(page_state, 'factor_family_alias', '') or '')
        except Exception:
            pass
    # Allow override from request (same as SSE handler)
    req_family = data.get('factor_family_alias')
    if req_family:
        factor_family_alias = str(req_family)

    # ── Factor inputs & calendar ──
    auto_group_calendar_freq = bool(data.get('auto_group_calendar_freq', True))
    requested_group_calendar_freq = None if auto_group_calendar_freq else data.get('group_calendar_freq')
    group_factor_params_list = data.get('_group_factor_params_list')
    if not isinstance(group_factor_params_list, list):
        group_factor_params_list = None
    group_owner_username = data.get('_group_owner_username')
    group_owner_username = str(group_owner_username) if group_owner_username else None

    # Ensure testers and factors
    tester0 = None
    for submission_id, factor_aliases in factor_aliases_by_submission.items():
        tester = runtime_state.get_factor_tester(submission_id, caller='run_group_test_prepare_factors')
        if tester0 is None:
            tester0 = tester
        _ensure_tester_factors_for_group(
            tester,
            factor_aliases,
            factor_family_alias,
            params_list=group_factor_params_list,
            username=group_owner_username,
        )
        for factor_alias in factor_aliases:
            factor = tester.resolve_factor(str(factor_alias))
            if factor is None:
                return False, {
                    'success': False,
                    'error': f'未找到因子 {factor_alias}。请确认当前因子参数已保存，或刷新页面后重试。',
                    'status': 400,
                }
            ensure_group_factor_inputs(
                tester,
                factor,
                returns_col=FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED,
            )

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
    try:
        effective_group_calendar_freq = FactorTester.resolve_group_calendar_freq_from_factor_freqs(
            all_factor_freqs,
            'auto' if auto_group_calendar_freq else requested_group_calendar_freq,
        )
    except ValueError as exc:
        return False, {'success': False, 'error': str(exc), 'status': 400}
    _progress(
        f"calendar resolve done effective_freq={effective_group_calendar_freq} "
        f"factor_freq_count={len(all_factor_freqs)}"
    )
    for submission_id, factor_aliases in factor_aliases_by_submission.items():
        tester = runtime_state.get_factor_tester(submission_id, caller='run_group_test_calendar_build')
        tester_calendar = tester.build_group_calendar_index(
            factor_aliases,
            requested_calendar_freq=effective_group_calendar_freq,
        )
        if len(tester_calendar) > 0:
            calendar_indices.append(tester_calendar)
    global_calendar_index = tester0.merge_group_calendar_indices(calendar_indices) if tester0 else pd.Index([])

    # ── Fee: resolve per-spec from group fields ──
    # Default: uniform fee=0, no closetoday
    fee_uniform = 0.0
    fee_modifications = None
    use_closetoday = False
    # Scan groups for fee config (first non-none uniform or per_product wins)
    for g in flat_groups_raw:
        fm = g.get('feeMode') or g.get('fee_mode')
        if fm == 'uniform':
            fee_uniform = float(g.get('feeRate', g.get('fee_rate', 0.0025)) or 0.0025)
            break
        elif fm == 'per_product':
            fee_uniform = 0.0
            fee_modifications = g.get('feeModifications') or g.get('fee_modifications') or None
            break
    for g in flat_groups_raw:
        if g.get('useCloseToday') or g.get('use_closetoday'):
            use_closetoday = True
            break

    # ── Run FactorGroupTester ──
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
    errors = []
    try:
        raw_results = group_tester.run(
            fee=fee_uniform,
            fee_modifications=fee_modifications,
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

    submission_results: list[dict | None] = [None] * sim_index
    for raw_result in raw_results:
        idx = int(raw_result.get('simulation_index', -1))
        if idx < 0 or idx >= sim_index:
            continue
        flat_info = raw_result.get('flat_group_info')
        serialized = _serialize_group_simulation_result(
            tester=raw_result['tester'],
            submission_id=str(raw_result.get('submission_id') or ''),
            factor_alias=str(raw_result.get('factor_alias') or ''),
            n_groups=int(raw_result.get('n_groups', 5)),
            ls_configs=raw_result.get('ls_configs'),
            rebalance_mode=rebalance_mode,
            simulation_result=raw_result,
            flat_group_info=flat_info if isinstance(flat_info, list) and flat_info else None,
        )
        serialized['submission_id'] = str(raw_result.get('submission_id') or '')
        serialized['factor_alias'] = str(raw_result.get('factor_alias') or '')
        serialized['n_groups_requested'] = int(raw_result.get('n_groups', 5))
        serialized['simulation_index'] = idx
        submission_results[idx] = serialized
        _progress(f"group tester accepted index={idx + 1}/{sim_index}")

    valid_results = [r for r in submission_results if r is not None]
    _progress(f"submission parallel done valid={len(valid_results)} errors={len(errors)}")
    if not valid_results:
        first_err = errors[0] if errors else {'error': '所有提交条目均失败'}
        return False, {
            'success': False,
            'error': first_err.get('error', '所有提交条目均失败'),
            'traceback': first_err.get('traceback'),
            'simulation_errors': errors,
            'status': 500,
        }

    # ── Per-entry LS configs are already computed inside each simulation result. ──
    # Future: if ls_configs legs span different specs (cross-tester LS),
    # build_overlap_batches merges those specs into one product_coverage_batch,
    # so the LS computation happens naturally inside FactorGroupTester.run().

    # ── Merge results ──
    cross_ls_groups: list[dict] = []
    cross_ls_metrics: dict = {}
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
            merged_groups.append(group)
            if original_key in cross_ls_metrics:
                merged_metrics[merged_key] = cross_ls_metrics[original_key]

    _progress(
        f"group simulations request done groups={len(merged_groups)} metrics={len(merged_metrics)} "
        f"elapsed={time.perf_counter() - request_started:.2f}s"
    )
    first_valid = valid_results[0] if valid_results else {}
    return True, {
        'success': True,
        'groups': merged_groups,
        'metrics': merged_metrics,
        'metrics_meta': _get_metrics_meta(),
        'n_groups': last_n_groups,
        'multi_session_active': last_multi_session,
        'multi_session_entries': multi_session_entries,
        'rebalance_mode': last_rebalance,
        'submission_id': first_valid.get('submission_id', ''),
        'factor_alias': first_valid.get('factor_alias', ''),
        'tester_alias': first_valid.get('tester_alias', '?') if valid_results else '?',
        'tester_product_count': first_valid.get('tester_product_count', 0),
        'simulation_count': len(valid_results),
        'cross_entry_ls_count': len(cross_ls_groups),
        'errors': errors if errors else None,
    }

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
                # hold_np shape: (T, M, P)；M 可能 > n_groups（LS 扩展等）
                if g < hold_np.shape[1]:
                    g_amounts = hold_np[t_idx, g, :]  # (P,) — 该组每产品持仓金额
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
            group_result.open_ratio_vec if group_result is not None else None,
            group_result.close_ratio_vec if group_result is not None else None,
            group_result.close_today_ratio_vec if group_result is not None else None,
        )
        return jsonify({'success': True, 'detail': detail})
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
                    info['n_groups'] = gr.returns_np.shape[1] if hasattr(gr, 'returns_np') and gr.returns_np is not None else None
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


# ═══════════════════════════════════════════════════
#  SSE 流式端点
# ═══════════════════════════════════════════════════

@sft_bp.route('/run_group_test_stream', methods=['POST'])
def run_group_test_stream():
    """SSE 流式分组测试——推送 batch/membership/simulate 进度 + 最终结果。"""
    import threading
    import json as _json
    from flask import Response, stream_with_context
    from server.services.sse_progress import SSEProgressEmitter
    from tools.factors.backtest_progress import BacktestProgressRegistry
    from tools.factors.tests.single_factor_test.group.core import (
        register_group_progress,
        unregister_group_progress,
    )

    data = request.get_json(silent=True) or {}

    # ── 在主线程中完成 data 校验 ──
    flat_groups_raw = data.get('groups')
    if not isinstance(flat_groups_raw, list) or not flat_groups_raw:
        def _early_err():
            yield f"event: error\ndata: {_json.dumps({'success': False, 'error': 'groups 必须是非空数组'}, default=str)}\n\n"
        return Response(_early_err(), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    # ── Resolve factor_family_alias from page_uuid ──
    page_uuid = str(data.get('page_uuid') or '')
    factor_family_alias = ''
    if page_uuid:
        try:
            page_state = runtime_state.get_page_state(page_uuid)
            factor_family_alias = str(getattr(page_state, 'factor_family_alias', '') or '')
        except Exception:
            pass
    # Allow override from request
    req_family = data.get('factor_family_alias')
    if req_family:
        factor_family_alias = str(req_family)
    if factor_family_alias:
        try:
            factor_family = get_factor_family_instance(
                factor_family_alias,
                username=runtime_state.current_user(),
            )
            data = dict(data)
            data['_group_owner_username'] = runtime_state.current_user()
            data['_group_factor_params_list'] = runtime_state.get_session_params(
                factor_family_alias,
                factor_family,
            )
        except Exception as exc:
            def _early_factor_err():
                yield f"event: error\ndata: {_json.dumps({'success': False, 'error': f'准备分组测试因子参数失败: {exc}'}, default=str)}\n\n"
            return Response(_early_factor_err(), mimetype='text/event-stream',
                            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    emitter = SSEProgressEmitter()
    registry = BacktestProgressRegistry()

    # ── 将 registry 的三个生命周期回调桥接到 SSE emitter ──
    registry.register_before(
        lambda total, groups, phase, extra: emitter.emit_start(
            total=total, groups=groups, phase=phase, **extra,
        )
    )
    registry.register_phase(
        lambda phase, message, completed, total, extra: emitter.emit_progress(
            completed=completed, total=total, phase=phase, message=message, **extra,
        )
    )
    registry.register_after(
        lambda success, data: emitter.emit_result(data) if success else emitter.emit_error(
            data.get('error', '未知错误'),
            traceback=data.get('traceback', ''),
        )
    )

    def _compute_and_emit():
        try:
            # ── 将 registry 桥接到 core.py 的全局注册 ──
            last_progress = {'completed': 0, 'total': 0}
            last_progress_by_batch: dict[int, dict[str, int]] = {}

            def _progress_bridge(phase: str, message: str, extra: dict):
                progress_extra = dict(extra)
                completed = extra.get('completed')
                total = extra.get('total', extra.get('total_batches'))
                product_coverage_batch_index = extra.get('product_coverage_batch_index')
                has_progress_count = completed is not None and total is not None
                if has_progress_count:
                    last_progress['completed'] = completed
                    last_progress['total'] = total
                    if product_coverage_batch_index is not None:
                        last_progress_by_batch[int(product_coverage_batch_index)] = {
                            'completed': completed,
                            'total': total,
                        }
                elif phase == 'info':
                    batch_progress = None
                    if product_coverage_batch_index is not None:
                        batch_progress = last_progress_by_batch.get(int(product_coverage_batch_index))
                    progress = batch_progress or last_progress
                    completed = progress['completed']
                    total = progress['total']
                    progress_extra['completed'] = completed
                    progress_extra['total'] = total
                elif phase != 'init':
                    return
                completed = completed or 0
                total = total or 0
                progress_extra.pop('completed', None)
                progress_extra.pop('total', None)
                if phase == 'init':
                    registry.emit_start(
                        total=total, groups=extra.get('total_groups', 0),
                        phase='product_coverage_batch',
                        phases=extra.get('phases', []),
                        **progress_extra,
                    )
                else:
                    registry.emit_phase(
                        phase, message=message,
                        completed=completed, total=total,
                        **progress_extra,
                    )

            register_group_progress(_progress_bridge)

            success, result = _run_group_test_core(data)
            if success:
                registry.emit_result(result)
            else:
                registry.emit_error(
                    result.get('error', '未知错误'),
                    traceback=result.get('traceback', ''),
                )
        except Exception as e:
            import traceback as _tb
            registry.emit_error(str(e), traceback=_tb.format_exc())
        finally:
            unregister_group_progress()
            registry.cleanup()
            emitter.close()

    threading.Thread(target=_compute_and_emit, daemon=True).start()
    return emitter.get_response()
