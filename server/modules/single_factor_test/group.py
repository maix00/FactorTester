"""
Group test endpoint: /run_group_test
"""
import math, traceback
import numpy as np
import pandas as pd
from flask import request, jsonify
from tools.factors.FactorFamily import _active_tester
from . import sft_bp
from server.shared import _factor_testers_lock
import server.shared as shared


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
    _gt_token = None
    try:
        with _factor_testers_lock:
            tester = next((t for t in shared.factor_testers if t.alias == str(submission_id)), None)
        if not tester:
            return jsonify({'success': False, 'error': '未找到测试器实例'}), 404

        factor = next((f for f in tester.factors if f.alias == factor_alias), None)
        if not factor:
            return jsonify({'success': False, 'error': f'未找到因子 {factor_alias}'}), 404

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

        from tools.factors.FactorTester import _signal_time
        _, _returns_dict, report_df, cum_np, idx_list = tester.test_by_group(
            factors=factor, n_groups=n_groups, time_range=time_range,
            plot_flag=False, save_plot=False, plot_show=False,
            fee=fee_uniform, fee_map=fee_map,
        )

        timestamps = [int(_signal_time(d).timestamp() * 1000) for d in idx_list]
        groups_data = []
        for g in range(n_groups):
            vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else None for v in cum_np[:, g]]
            groups_data.append({'name': f'Group {g+1}', 'timestamps': timestamps, 'cumulative_returns': vals})

        gross_np  = getattr(tester, '_last_group_gross_returns_np', None) or np.zeros((len(timestamps), n_groups))
        fee_np    = getattr(tester, '_last_fee_costs_np',            None) or np.zeros((len(timestamps), n_groups))
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

        s     = pd.Series(r_ls).replace([np.inf, -np.inf], np.nan).dropna()
        cum_s = (1 + s).cumprod()
        n     = len(s)
        def _safe(v): return None if (math.isnan(v) or math.isinf(v)) else round(float(v), 6)
        dd = (cum_s.cummax() - cum_s) / cum_s.cummax()
        ls_annual = _safe((cum_s.iloc[-1] ** (252 / n) - 1) * 100) if n > 1 else None
        ls_dd     = _safe(dd.max() * 100) if n > 0 else None
        ls_metric = {
            'Total Return':  _safe((cum_s.iloc[-1] - 1) * 100) if n > 0 else None,
            'Annual Return': ls_annual,
            'Volatility':    _safe(s.std() * (252 ** 0.5) * 100),
            'Sharpe Ratio':  _safe((s.mean() * 252) / (s.std() * 252**0.5)) if s.std() != 0 else None,
            'Max Drawdown':  ls_dd,
            'Calmar Ratio':  _safe(float(ls_annual) / float(ls_dd)) if (ls_annual and ls_dd) else None,  # type: ignore[arg-type]
            'Win Rate':      _safe((s > 0).sum() / n * 100) if n > 0 else None,
            'Mean Return':   _safe(s.mean() * 100),
            'Skewness':      _safe(float(s.skew())),
            'Kurtosis':      _safe(float(s.kurtosis())),
        }

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
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if _gt_token is not None:
            _active_tester.reset(_gt_token)
