"""
Group test endpoint: /run_group_test /run_multi_horizon_group_test
"""
import math, traceback
import numpy as np
import pandas as pd
from flask import request, jsonify
from tools.factors.FactorTester import _active_tester
from tools.data.DataFreq import DataFreq
from . import sft_bp
from server.shared import _factor_testers_lock
import server.shared as shared


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
    start_date = data.get('start_date')
    end_date   = data.get('end_date')
    # 多周期对比：传入 return_freqs 数组，如 ["1d","3d","5d","10d"]
    return_freqs: list = data.get('return_freqs', None)
    _gt_token = None
    try:
        with _factor_testers_lock:
            target_suffix = f":{submission_id}"
            tester = next((t for t in shared.factor_testers if t.alias == str(submission_id) or t.alias.endswith(target_suffix)), None)
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
            multi_horizon_results = []
            for rf_str in return_freqs:
                try:
                    freq = DataFreq(rf_str) if rf_str else None
                except Exception:
                    freq = None
                factor.calc_returns(next_return=True, return_freq=freq)
                from tools.factors.FactorTester import _signal_time
                _, _returns_dict, report_df, cum_np, idx_list = tester.test_by_group(
                    factors=factor, n_groups=n_groups, time_range=time_range,
                    plot_flag=False, save_plot=False, plot_show=False,
                    fee=fee_uniform, fee_map=fee_map,
                )
                timestamps = [int(_signal_time(d).timestamp() * 1000) for d in idx_list]
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
            return jsonify({'success': True, 'multi_horizon': True, 'results': multi_horizon_results, 'n_groups': n_groups})

        # ─── 原有单频率逻辑 ───
        from tools.factors.FactorTester import _signal_time
        _, _returns_dict, report_df, cum_np, idx_list = tester.test_by_group(
            factors=factor, n_groups=n_groups, time_range=time_range,
            plot_flag=False, save_plot=False, plot_show=False,
            fee=fee_uniform, fee_map=fee_map,
        )

        timestamps = [int(_signal_time(d).timestamp() * 1000) for d in idx_list]

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

        return jsonify({'success': True, 'groups': groups_data, 'metrics': metrics, 'n_groups': n_groups})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})
    finally:
        if _gt_token is not None:
            _active_tester.reset(_gt_token)
