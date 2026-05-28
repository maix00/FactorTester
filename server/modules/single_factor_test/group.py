"""
Group test endpoint: /run_group_test /run_multi_horizon_group_test
"""
import logging, math, traceback
from typing import cast
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


def _serialize_float_series(values: np.ndarray | list, default=0.0) -> list:
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
            group = int(item.get('group'))
            weight = float(item.get('weight'))
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
    raw_configs = data.get('ls_configs')
    if isinstance(raw_configs, list) and raw_configs:
        configs = []
        for raw in raw_configs:
            if not isinstance(raw, dict):
                continue
            configs.append(_parse_ls_config({'ls_config': raw}, n_groups))
        return configs or [_parse_ls_config(data, n_groups)]
    return [_parse_ls_config(data, n_groups)]


def _unique_metric_key(name: str, used: set[str], default: str = 'LS') -> str:
    base = name or default
    key = default if base == 'Long-Short' and default not in used else base
    suffix = 2
    while key in used:
        key = f'{base} #{suffix}'
        suffix += 1
    used.add(key)
    return key


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


def _build_derived_group_payload(group_result, group_index: int, product_names: list[str], name: str) -> tuple[dict, dict]:
    from tools.products.product_utils import product_display_name

    contrib = getattr(group_result, 'product_gross_contrib_np', None)
    valid_cols = getattr(group_result, 'valid_cols', None)
    idx_list = getattr(group_result, 'index_list', None) or []
    if contrib is None or valid_cols is None:
        raise ValueError('当前分组结果缺少逐品种贡献，无法生成派生组')
    contrib_np = np.asarray(contrib, dtype=float)
    if contrib_np.ndim != 3 or group_index < 0 or group_index >= contrib_np.shape[1]:
        raise ValueError('基准组不存在或逐品种贡献维度异常')

    display_names = [product_display_name(product)['name'] for product in valid_cols]
    selected = {str(name) for name in (product_names or [])}
    selected_idx = [idx for idx, display_name in enumerate(display_names) if display_name in selected]
    if not selected_idx:
        raise ValueError('请至少选择一个有效品种')

    returns = np.nan_to_num(contrib_np[:, group_index, selected_idx].sum(axis=1), nan=0.0, posinf=0.0, neginf=0.0)
    cumulative = _returns_to_cumulative(returns)
    timestamps = [to_utc_epoch(_signal_time(d)) for d in idx_list]
    metric = _compute_return_metrics(returns, index_like=idx_list, avg_turnover=None)
    group = {
        'name': name or f'第{group_index + 1}组精选',
        'timestamps': timestamps,
        'cumulative_returns': _serialize_float_series(cumulative, default=None),
        'gross_returns': _serialize_float_series(returns, default=0.0),
        'fee_costs': [0.0] * len(returns),
        'trade_notional_ratios': [0.0] * len(returns),
        'is_derived': True,
        'derived': {
            'base_group': group_index,
            'product_names': [display_names[idx] for idx in selected_idx],
        },
    }
    return group, metric


def _latest_group_result(tester):
    factor = getattr(tester, 'last_group_factor', None)
    if factor is None:
        return None
    result = tester.results.get(factor) if hasattr(tester, 'results') else None
    return result.group_result if result is not None else None


def _parse_group_fee_config(data):
    fee_uniform = float(data.get('fee', 0.0) or 0.0) / 100.0
    fee_map_raw = data.get('fee_map', {}) or {}
    use_closetoday = bool(data.get('use_closetoday', False))

    fee_map: dict[str, dict[str, float]] = {}
    for code, rates in fee_map_raw.items():
        open_r = float(rates.get('open_ratio', 0) or 0)
        close_r = float(rates.get('close_ratio', 0) or 0)
        close_today_r = float(rates.get('closetoday_ratio', close_r) or 0)
        selected_close_r = close_today_r if use_closetoday else close_r
        if open_r > 0 or close_r > 0 or close_today_r > 0:
            fee_map[str(code).upper()] = {
                'open': open_r,
                'close': selected_close_r,
                'close_today': close_today_r,
                'close_yesterday': close_r,
            }

    return fee_uniform, fee_map, use_closetoday


def _product_fee_rates_by_name(group_result) -> dict[str, dict[str, float]]:
    """返回 {产品名: {open, close, close_today, close_yesterday, total, _is_real_fee}} 的费率字典。

    如果回测中用户未设置费率（所有品种费率均为 0），
    则从全局产品费率表 (sources.FeeData) 获取真实费率，
    并标记 _is_real_fee=True 提示前端显示"原始费率"标注。
    """
    valid_cols = getattr(group_result, 'valid_cols', None)
    open_fee_vec = getattr(group_result, 'open_fee_vec', None)
    close_fee_vec = getattr(group_result, 'close_fee_vec', None)
    close_today_fee_vec = getattr(group_result, 'close_today_fee_vec', None)
    if not valid_cols or open_fee_vec is None or close_fee_vec is None:
        return {}
    from tools.products.product_utils import product_display_name

    open_rates = np.asarray(open_fee_vec, dtype=float)
    close_rates = np.asarray(close_fee_vec, dtype=float)
    close_today_rates = (
        np.asarray(close_today_fee_vec, dtype=float)
        if close_today_fee_vec is not None else close_rates
    )
    if len(valid_cols) != open_rates.shape[0] or len(valid_cols) != close_rates.shape[0]:
        return {}

    # 判断用户是否设置了费率：所有品种费率均为 0 → 未设置
    user_has_fee = bool(np.any(open_rates > 0) or np.any(close_rates > 0))

    # 如果用户未设置费率，从全局费率表获取真实费率
    use_real_fee = not user_has_fee
    if use_real_fee:
        from sources.FeeData import load_latest
        df_fees = load_latest()
        fee_by_code = {}
        if not df_fees.empty:
            for _, row in df_fees.iterrows():
                fee_by_code[str(row['variety_code']).upper()] = row

    rates = {}
    for idx, product in enumerate(valid_cols):
        name = product_display_name(product)['name']
        if use_real_fee:
            code = str(product if isinstance(product, str) else getattr(product, 'name', product)).split('.')[0].upper()
            variety_fee = fee_by_code.get(code)
            if variety_fee is not None:
                o = float(variety_fee['open_ratio']) if pd.notna(variety_fee['open_ratio']) else 0.0
                c = float(variety_fee['close_ratio']) if pd.notna(variety_fee['close_ratio']) else 0.0
                ct = float(variety_fee['closetoday_ratio']) if pd.notna(variety_fee['closetoday_ratio']) else c
            else:
                o = c = ct = 0.0
        else:
            o = float(open_rates[idx])
            c = float(close_rates[idx])
            ct = float(close_today_rates[idx])
        rates[name] = {
            'open': o,
            'close': c,
            'close_today': ct,
            'close_yesterday': c,
            'total': o + c,
            '_is_real_fee': use_real_fee,
        }
    return rates


def _display_product_with_fee(product, fee_rates_by_name: dict[str, dict[str, float]]) -> dict:
    from tools.products.product_utils import product_display_name

    display = product_display_name(product)
    display['fee'] = fee_rates_by_name.get(display['name'])
    return display


@sft_bp.route('/run_group_test', methods=['POST'])
def run_group_test():
    data = request.get_json()
    submission_id  = data.get('submission_id')
    factor_alias   = data.get('factor_alias')
    n_groups       = data.get('n_groups', 5)
    fee_uniform, fee_map, use_closetoday = _parse_group_fee_config(data)
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
                    rebalance_mode=rebalance_mode,
                )
                # ... (computation logic unchanged) ...
                timestamps = [to_utc_epoch(_signal_time(d)) for d in idx_list]
                group_result = tester._get_result(factor).group_result
                _gross = group_result.gross_returns_np if group_result is not None else None
                gross_np = _gross if _gross is not None else np.zeros((len(timestamps), n_groups))
                _fee_np = group_result.fee_costs_np if group_result is not None else None
                fee_np_arr = _fee_np if _fee_np is not None else np.zeros((len(timestamps), n_groups))

                r_ls_np, _ = _compute_weighted_ls_returns(gross_np, fee_np_arr, ls_configs[0], n_groups)
                ls_metric = _compute_ls_metrics(r_ls_np, report_df, idx_list)
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
            
            return jsonify({'success': True, 'multi_horizon': True, 'results': multi_horizon_results, 'n_groups': n_groups,
                            'structure_key': data.get('structure_key'),
                            'multi_session_active': bool(group_result.multi_session_active) if group_result is not None else False,
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
            rebalance_mode=rebalance_mode,
        )

        timestamps = [to_utc_epoch(_signal_time(d)) for d in idx_list]

        group_result = tester._get_result(factor).group_result
        _gross = group_result.gross_returns_np if group_result is not None else None
        gross_np = _gross if _gross is not None else np.zeros((len(timestamps), n_groups))
        _fee = group_result.fee_costs_np if group_result is not None else None
        fee_np = _fee if _fee is not None else np.zeros((len(timestamps), n_groups))

        groups_data = []
        for g in range(n_groups):
            vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else None for v in cum_np[:, g]]
            gross_vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else 0.0 for v in gross_np[:, g]]
            fee_vals   = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else 0.0 for v in fee_np[:, g]]
            groups_data.append({
                'name': f'Group {g+1}',
                'timestamps': timestamps,
                'cumulative_returns': vals,
                'gross_returns': gross_vals,
                'fee_costs': fee_vals,
                'trade_notional_ratios': [
                    round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else 0.0
                    for v in group_result.trade_notional_ratio_np[:, g]
                ] if group_result is not None and group_result.trade_notional_ratio_np is not None else [],
            })

        metrics: dict = {}
        if not report_df.empty:
            metrics = {
                str(k): {mk: (None if mv is None or (isinstance(mv, float) and (math.isnan(mv) or math.isinf(mv))) else float(mv))
                         for mk, mv in v.items()}
                for k, v in report_df.to_dict(orient='index').items()
            }
        used_metric_keys = set(metrics.keys())
        for ls_config in ls_configs:
            r_ls, ls_cum_arr = _compute_weighted_ls_returns(gross_np, fee_np, ls_config, n_groups)
            metric_key = _unique_metric_key(ls_config['name'], used_metric_keys, default='LS')
            ls_vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else None for v in ls_cum_arr]
            groups_data.append({
                'name': ls_config['name'],
                'metric_key': metric_key,
                'timestamps': timestamps,
                'cumulative_returns': ls_vals,
                'gross_returns': _serialize_float_series(r_ls, default=0.0),
                'fee_costs': [0.0] * len(r_ls),
                'trade_notional_ratios': [0.0] * len(r_ls),
                'is_ls': True,
                'is_derived': True,
                'derived': {'type': 'long_short', 'metric_key': metric_key, 'config': ls_config},
            })
            metrics[metric_key] = _compute_ls_metrics(r_ls, report_df, idx_list)

        return jsonify({'success': True, 'groups': groups_data, 'metrics': metrics, 'n_groups': n_groups,
                        'structure_key': data.get('structure_key'),
                        'multi_session_active': bool(group_result.multi_session_active) if group_result is not None else False,
                        'rebalance_mode': rebalance_mode,
                        'submission_id': submission_id, 'factor_alias': factor_alias,
                        'tester_alias': getattr(tester, 'alias', '?'),
                        'tester_product_count': len(tester.products) if hasattr(tester, 'products') else 0})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})
    finally:
        if _saved_products is not None:
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
        valid_cols = group_result.valid_cols if group_result is not None else None
        if not products_dict or not valid_cols:
            return jsonify({'success': False, 'error': '未找到最近的分组测试结果，请先运行分组测试'}), 400

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

        # 找到上一时刻
        sorted_entries = sorted(first_group.keys(), key=lambda e: _signal_time(e))
        current_pos = sorted_entries.index(best_idx_entry)
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


@sft_bp.route('/create_derived_group', methods=['POST'])
def create_derived_group():
    """Create a chart/metric payload for a user-defined product subset group."""
    data = request.get_json() or {}
    submission_id = data.get('submission_id')
    group_index = data.get('group_index')
    product_names = data.get('product_names') or []
    name = str(data.get('name') or '').strip()
    if submission_id is None or group_index is None:
        return jsonify({'success': False, 'error': '缺少 submission_id 或 group_index'}), 400
    try:
        tester = runtime_state.get_factor_tester(submission_id, caller='create_derived_group')
        group_result = _latest_group_result(tester)
        if group_result is None:
            return jsonify({'success': False, 'error': '未找到最近的分组测试结果，请先运行分组测试'}), 400
        group, metric = _build_derived_group_payload(
            group_result,
            int(group_index),
            [str(x) for x in product_names],
            name or f'第{int(group_index) + 1}组精选',
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
