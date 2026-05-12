"""
Group test endpoint: /run_group_test /run_multi_horizon_group_test
"""
import math, traceback
from typing import cast
import numpy as np
import pandas as pd
from flask import request, jsonify
from tools.factors.FactorTester import _active_tester, _signal_time
from tools.factors.FactorRunResult import FactorRunResult
from tools.data.DataFreq import DataFreq
from . import sft_bp
import server.services.runtime_state as runtime_state
from server.modules.shared.price_data_helpers import to_utc_epoch


def _safe_float(v):
    """安全转为 float，NaN/inf 返回 None。"""
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(fv) or math.isinf(fv)) else fv


def _compute_ls_metrics(r_ls_array: np.ndarray, report_df: pd.DataFrame) -> dict:
    """从 Long-Short 收益率序列计算绩效指标。"""
    s = pd.Series(r_ls_array).replace([np.inf, -np.inf], np.nan).dropna()
    n = len(s)
    if n == 0:
        return {}
    cum_s = (1 + s).cumprod()
    dd = (cum_s.cummax() - cum_s) / cum_s.cummax()
    ls_annual = _safe_float((cum_s.iloc[-1] ** (252 / n) - 1) * 100) if n > 1 else None
    ls_dd = _safe_float(dd.max() * 100) if n > 0 else None
    return {
        'Total Return':  _safe_float((cum_s.iloc[-1] - 1) * 100) if n > 0 else None,
        'Annual Return': ls_annual,
        'Volatility':    _safe_float(s.std() * (252 ** 0.5) * 100),
        'Sharpe Ratio':  _safe_float((s.mean() * 252) / (s.std() * 252**0.5)) if s.std() != 0 else None,
        'Max Drawdown':  ls_dd,
        'Calmar Ratio':  _safe_float(float(ls_annual) / float(ls_dd)) if (ls_annual and ls_dd) else None,
        'Win Rate':      _safe_float((s > 0).sum() / n * 100) if n > 0 else None,
        'Mean Return':   _safe_float(s.mean() * 100),
        'Skewness':      _safe_float(s.skew()),
        'Kurtosis':      _safe_float(s.kurtosis()),
        'Avg Turnover':  round(float(
            (report_df['Avg Turnover'].iloc[0] + report_df['Avg Turnover'].iloc[-1]) / 2
        ), 4) if not report_df.empty and 'Avg Turnover' in report_df.columns else None,
    }


@sft_bp.route('/run_group_test', methods=['POST'])
def run_group_test():
    data = request.get_json()
    submission_id  = data.get('submission_id')
    factor_alias   = data.get('factor_alias')
    n_groups       = data.get('n_groups', 5)
    fee_uniform    = float(data.get('fee', 0.0) or 0.0) / 100.0
    fee_map_raw: dict = data.get('fee_map', {})
    use_closetoday: bool = bool(data.get('use_closetoday', False))
    rebalance_mode: str = str(data.get('rebalance_mode', 'each_period') or 'each_period')
    start_date = data.get('start_date')
    end_date   = data.get('end_date')
    # 多周期对比：传入 return_freqs 数组，如 ["1d","3d","5d","10d"]
    return_freqs: list = data.get('return_freqs', None)
    _gt_token = None
    try:
        tester = runtime_state.find_factor_tester(submission_id, allow_suffix=True)
        if not tester:
            return jsonify({'success': False, 'error': '未找到测试器实例'}), 404

        factor = next((f for f in tester.factors if f.alias == factor_alias or f.name == factor_alias), None)
        if not factor:
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

        fee_map: dict[str, dict[str, float]] = {}
        for code, rates in fee_map_raw.items():
            open_r  = float(rates.get('open_ratio', 0) or 0)
            ct_key  = 'closetoday_ratio' if use_closetoday else 'close_ratio'
            close_r = float(rates.get(ct_key, 0) or 0)
            if open_r > 0 or close_r > 0:
                fee_map[str(code).upper()] = {'open': open_r, 'close': close_r}

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
                _gross = getattr(tester, '_last_group_gross_returns_np', None)
                gross_np = _gross if _gross is not None else np.zeros((len(timestamps), n_groups))
                _fee_np = getattr(tester, '_last_fee_costs_np', None)
                fee_np_arr = _fee_np if _fee_np is not None else np.zeros((len(timestamps), n_groups))

                long_net  = (1.0 - fee_np_arr[:, 0]) * (1.0 + gross_np[:, 0]) - 1.0
                short_net = (1.0 - fee_np_arr[:, n_groups - 1]) * (1.0 - gross_np[:, n_groups-1]) - 1.0

                long_cap = short_cap = 0.5
                total_cap = 1.0
                r_ls_arr = []
                for rl, rs in zip(long_net, short_net):
                    rl = 0.0 if (np.isnan(rl) or np.isinf(rl)) else float(rl)
                    rs = 0.0 if (np.isnan(rs) or np.isinf(rs)) else float(rs)
                    long_cap  *= (1.0 + rl)
                    short_cap *= (1.0 + rs)
                    new_total  = long_cap + short_cap
                    r_ls_arr.append(new_total / total_cap - 1.0)
                    total_cap = new_total

                r_ls_np = np.array(r_ls_arr, dtype=float)
                ls_metric = _compute_ls_metrics(r_ls_np, report_df)
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
                            'multi_session_active': getattr(tester, '_last_multi_session_active', False),
                            'rebalance_mode': rebalance_mode})

        # ─── 原有单频率逻辑 ───
        _, _returns_dict, report_df, cum_np, idx_list = tester.test_by_group(
            factors=factor, n_groups=n_groups, time_range=time_range,
            plot_flag=False, save_plot=False, plot_show=False,
            fee=fee_uniform, fee_map=fee_map,
            rebalance_mode=rebalance_mode,
        )

        timestamps = [to_utc_epoch(_signal_time(d)) for d in idx_list]

        _gross = getattr(tester, '_last_group_gross_returns_np', None)
        gross_np = _gross if _gross is not None else np.zeros((len(timestamps), n_groups))
        _fee = getattr(tester, '_last_fee_costs_np', None)
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
            })

        long_net  = (1.0 - fee_np[:, 0])           * (1.0 + gross_np[:, 0])          - 1.0
        short_net = (1.0 - fee_np[:, n_groups - 1]) * (1.0 - gross_np[:, n_groups-1]) - 1.0

        long_cap = short_cap = 0.5
        total_cap = 1.0
        ls_cum_list: list = []
        r_ls_list:   list = []
        for rl, rs in zip(long_net, short_net):
            rl = 0.0 if (np.isnan(rl) or np.isinf(rl)) else float(rl)
            rs = 0.0 if (np.isnan(rs) or np.isinf(rs)) else float(rs)
            long_cap  *= (1.0 + rl)
            short_cap *= (1.0 + rs)
            new_total  = long_cap + short_cap
            r_ls_list.append(new_total / total_cap - 1.0)
            ls_cum_list.append(new_total)
            total_cap = new_total

        r_ls       = np.array(r_ls_list, dtype=float)
        ls_cum_arr = np.array(ls_cum_list, dtype=float)
        ls_vals    = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else None for v in ls_cum_arr]
        groups_data.append({'name': 'Long-Short', 'timestamps': timestamps, 'cumulative_returns': ls_vals, 'is_ls': True})

        ls_metric = _compute_ls_metrics(r_ls, report_df)

        metrics: dict = {}
        if not report_df.empty:
            metrics = {
                str(k): {mk: (None if mv is None or (isinstance(mv, float) and (math.isnan(mv) or math.isinf(mv))) else float(mv))
                         for mk, mv in v.items()}
                for k, v in report_df.to_dict(orient='index').items()
            }
        metrics['LS'] = ls_metric

        return jsonify({'success': True, 'groups': groups_data, 'metrics': metrics, 'n_groups': n_groups,
                        'multi_session_active': getattr(tester, '_last_multi_session_active', False),
                        'rebalance_mode': rebalance_mode})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})
    finally:
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
        tester = runtime_state.find_factor_tester(submission_id, allow_suffix=True)
        if not tester:
            return jsonify({'success': False, 'error': '未找到测试器实例'}), 404

        products_dict = getattr(tester, '_last_group_products', None)
        valid_cols = getattr(tester, '_last_group_valid_cols', None)
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

        from tools.products.product_utils import product_display_name

        n_groups = len(products_dict)
        groups_detail = []
        for g in range(n_groups):
            current_raw = products_dict[g].get(best_idx_entry, [])
            current_display = [product_display_name(x) for x in current_raw]
            # 按 name 排序
            current_display.sort(key=lambda d: d['name'])

            if prev_entry is not None:
                prev_raw = products_dict[g].get(prev_entry, [])
                prev_display = [product_display_name(x) for x in prev_raw]
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
