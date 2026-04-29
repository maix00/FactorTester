"""
IC test endpoint: /run_ic_test
"""
import pickle, hashlib, traceback
import numpy as np
import pandas as pd
from pathlib import Path
from flask import request, jsonify
from tools.factors.FactorFamily import FactorFamily, _active_tester
from tools.products.Product import Product
from tools.data.DataFreq import DataFreq
from . import sft_bp
from server.shared import (
    get_factor_family_instance, _get_session_params,
    _factor_testers_lock,
)
import server.shared as shared


@sft_bp.route('/run_ic_test', methods=['POST'])
def run_ic_test():
    data = request.get_json()
    submission_id = data.get('submission_id')
    factor_family_alias = data.get('factor_family_alias')
    factor_alias_return_freq = data.get('factors', [])
    paths = data.get('paths', [])
    re_calc = data.get('re_calc', False)
    _token = None
    try:
        with _factor_testers_lock:
            tester = next((t for t in shared.factor_testers if t.alias == str(submission_id)), None)
        assert tester is not None, "未找到对应的测试器实例"

        factor_family = get_factor_family_instance(factor_family_alias)
        assert isinstance(factor_family, FactorFamily), "未找到对应的因子家族实例"

        tester.sync_signal_index = None
        tester.sync_signal_index_replaced = None
        _token = _active_tester.set(tester)

        factors = factor_family.get_factors(params_list=_get_session_params(factor_family_alias, factor_family))
        # 过滤：只保留在当前因子家族中实际存在的因子
        matched_factors = []
        matched_items = []
        for item in factor_alias_return_freq:
            f = next((f for f in factors if f.alias == item['alias']), None)
            if f is not None:
                matched_factors.append(f)
                matched_items.append(item)
        if not matched_factors:
            return jsonify({'error': '没有找到匹配的因子，请检查收益率频率设置中的因子是否属于当前因子家族'}), 400
        factors = matched_factors
        factor_alias_return_freq = matched_items
        return_freqs = {
            factor: (None if item.get('return_freq') in (None, '', 'N') else item.get('return_freq'))
            for factor, item in zip(factors, factor_alias_return_freq)
        }

        # 新功能参数
        ic_decay_lags = data.get('ic_decay_lags', None)      # [1, 2, 3, 5, 10, 20] 或 None 表示不计算
        rolling_window = data.get('rolling_window', None)     # 如 60、120、252，None 表示不计算滚动 IC

        cache_dir_ic     = Path('../data/cache/ic')
        cache_dir_factor = Path('../data/cache/factor')
        cache_dir_ic.mkdir(parents=True, exist_ok=True)
        cache_dir_factor.mkdir(parents=True, exist_ok=True)

        sorted_paths = sorted(paths)
        paths_hash = hashlib.md5(str(sorted_paths).encode()).hexdigest()
        scp_str = str(shared.start_calc_point).replace(':', '-').replace(' ', '_') if shared.start_calc_point else 'latest'
        start_date_str = str(tester.start_date).replace(':', '-').replace(' ', '_')
        end_date_str   = str(tester.end_date).replace(':', '-').replace(' ', '_')
        all_products = tester.products.copy()

        for factor in factors:
            run_products = all_products.copy()
            factor.clear()
            return_freq = return_freqs.get(factor, None)
            factor_series_cache = cache_dir_factor / f"{factor.alias}_{scp_str}.pkl"
            factor_ic_cache     = cache_dir_ic     / f"{paths_hash}_{factor.alias}_{return_freq}_{start_date_str}_{end_date_str}.pkl"

            table = None
            if not re_calc and factor_series_cache.exists():
                with open(factor_series_cache, 'rb') as f:
                    table, scp_cache = pickle.load(f)
                if shared.start_calc_point == scp_cache:
                    run_products = set(p for p in tester.products if p not in table.columns)
                else:
                    table = None
            if run_products:
                try:
                    tester.products = run_products.copy()
                    tester.calc_factor(factors=factor)
                except Exception as e:
                    return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})
                finally:
                    tester.products = all_products.copy()
                    if factor.table is None or factor.table.empty:
                        run_products = set()
            if table is None and (factor.table is None or factor.table.empty):
                raise ValueError("/run_ic_test: 无法计算因子数据，且缓存中无数据可用")
            if table is not None:
                if factor.table is None or factor.table.empty:
                    factor.table = table
                else:
                    for col in table.columns:
                        assert col not in factor.table.columns, f"/run_ic_test: 列名冲突: {col}"
                    factor.table = pd.concat([table, factor.table], axis=1)
            if factor.table is not None and not factor.table.empty:
                if not hasattr(factor, 'freq') or factor.freq is None:
                    factor.freq = factor.get_freq()
                factor._set_products()
            if run_products:
                with open(factor_series_cache, 'wb') as f:
                    pickle.dump((factor.table, shared.start_calc_point), f)
            run_products = all_products.copy()

            ic_series = None
            ic_stats  = None
            returns_table = pd.DataFrame()
            if not re_calc and factor_ic_cache.exists():
                with open(factor_ic_cache, 'rb') as f:
                    ic_s_c, ic_st_c, prods_c, rf_c, ret_c, sd_c, ed_c = pickle.load(f)
                if prods_c == run_products and rf_c == return_freq and sd_c == tester.start_date and ed_c == tester.end_date:
                    ic_series, ic_stats, returns_table, run_products = ic_s_c, ic_st_c, ret_c, set()
            if run_products:
                try:
                    ic_s_df, ic_st_df = tester.calc_ic(factors=factor, return_freq=return_freq)
                    returns_table = factor.returns
                    ic_series = ic_s_df.iloc[:, 0]
                    ic_stats  = ic_st_df.iloc[:, 0]
                except Exception as e:
                    return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})
            assert ic_series is not None and ic_stats is not None and not returns_table.empty, \
                "/run_ic_test: 无法计算IC数据，且缓存中无数据可用"
            factor.ic_series = ic_series
            factor.ic_stats  = ic_stats
            if run_products:
                with open(factor_ic_cache, 'wb') as f:
                    pickle.dump((factor.ic_series, factor.ic_stats, all_products, return_freq,
                                 returns_table, tester.start_date, tester.end_date), f)

        tester.products = all_products.copy()
        ic_stats_all = pd.concat([f.ic_stats for f in factors], axis=1)
        ic_stats_all.rename(columns=lambda x: x.alias if hasattr(x, 'alias') else str(x), inplace=True)
        columns = ic_stats_all.columns.tolist()
        rows    = ic_stats_all.to_dict(orient='records')
        indices = ic_stats_all.index.tolist()
        for i, row in enumerate(rows):
            row['index'] = indices[i]

        response: dict = {
            'success': True,
            'paths_hash': paths_hash,
            'ic_stats': {'columns': ['index'] + columns, 'rows': rows},
            'factors': [],
        }

        # ─── IC 衰减分析（多周期 IC decay）───
        ic_decay_results = {}  # factor.alias → [{'lag': 1, 'mean':..., 'ir':..., 't_stat':...}, ...]
        if ic_decay_lags and isinstance(ic_decay_lags, list) and len(ic_decay_lags) > 0:
            base_freqs = return_freqs.copy()
            for factor in factors:
                base_freq = base_freqs.get(factor, None)
                # 基准频率（用于计算 lag 步长）
                if base_freq is None:
                    base_freq_str = '1d'  # 默认日频
                else:
                    base_freq_str = base_freq
                try:
                    base_td = pd.Timedelta(base_freq_str)
                except Exception:
                    base_td = pd.Timedelta('1d')
                decay_list = []
                for lag in ic_decay_lags:
                    try:
                        lag_td = base_td * int(lag)
                        ic_s_df_lag, ic_st_df_lag = tester.calc_ic(
                            factors=factor, return_freq=DataFreq(lag_td)
                        )
                        ic_s_lag = ic_s_df_lag.iloc[:, 0].dropna()
                        if len(ic_s_lag) > 1:
                            mean_val = float(ic_s_lag.mean())
                            std_val = float(ic_s_lag.std())
                            ir_val = mean_val / std_val if std_val != 0 else None
                            n_val = len(ic_s_lag)
                            t_stat_val = (mean_val / (std_val / np.sqrt(n_val))) if std_val != 0 and n_val > 1 else None
                            decay_list.append({
                                'lag': int(lag),
                                'mean': round(mean_val, 6),
                                'std': round(std_val, 6),
                                'ir': round(ir_val, 6) if ir_val is not None else None,
                                't_stat': round(t_stat_val, 6) if t_stat_val is not None else None,
                                'n': n_val,
                            })
                        else:
                            decay_list.append({'lag': int(lag), 'mean': None, 'std': None, 'ir': None, 't_stat': None, 'n': 0})
                    except Exception:
                        decay_list.append({'lag': int(lag), 'mean': None, 'std': None, 'ir': None, 't_stat': None, 'n': 0})
                ic_decay_results[factor.alias] = decay_list
                # 恢复原始 base 频率（后续代码依赖）
                return_freqs[factor] = base_freq

        for factor in factors:
            ic_s = factor.ic_series.dropna()
            if isinstance(ic_s.index, pd.MultiIndex):
                _sig = next((str(n) for n in ic_s.index.names if str(n).startswith('_SIGNAL')), None)
                _lvl = ic_s.index.names.index(_sig) if _sig else -1
                signal_ts = pd.DatetimeIndex(ic_s.index.get_level_values(_lvl))
            else:
                signal_ts = pd.DatetimeIndex(ic_s.index)
            _daily = factor.freq is not None and factor.freq.is_day_multiple()
            dates = [ts.strftime('%Y-%m-%d') for ts in signal_ts] if _daily else (signal_ts.view(np.int64) // 10**6).tolist()
            vals  = [None if (isinstance(v, float) and (pd.isna(v) or pd.isnull(v))) else v for v in ic_s.values.tolist()]

            # 自相关衰减序列 (lag 1~min(20, len/2-1))
            autocorr = None
            s = ic_s.dropna()
            if len(s) > 2:
                from statsmodels.tsa.stattools import acf
                try:
                    nlags = min(20, max(1, len(s) // 2 - 1))
                    acf_vals = acf(s.values, nlags=nlags, fft=False)
                    # 从 lag=1 开始，返回 [{'lag': 1, 'ac': ...}, ...]
                    autocorr = [{'lag': i, 'ac': round(float(v), 6)} for i, v in enumerate(acf_vals[1:], start=1)]
                except Exception:
                    pass

            # ─── 滚动窗口 IC ───
            rolling_ic = None
            if rolling_window and isinstance(rolling_window, (int, float)) and rolling_window > 1:
                win = int(rolling_window)
                s_vals = ic_s.dropna().values
                s_idx = ic_s.dropna().index
                if len(s_vals) >= win:
                    # 滚动计算每窗的 mean/IR
                    r_mean = []
                    r_ir = []
                    r_dates = []
                    for i in range(win - 1, len(s_vals)):
                        win_slice = s_vals[i - win + 1 : i + 1]
                        m = float(np.mean(win_slice))
                        std_win = float(np.std(win_slice))
                        r = m / std_win if std_win != 0 else None
                        r_mean.append(round(m, 6))
                        r_ir.append(round(r, 6) if r is not None else None)
                        ts_i = s_idx[i]
                        if hasattr(ts_i, 'strftime'):
                            r_dates.append(ts_i.strftime('%Y-%m-%d') if _daily else int(ts_i.value // 10**6))
                        else:
                            r_dates.append(str(ts_i))
                    rolling_ic = {
                        'window': win,
                        'dates': r_dates,
                        'mean': r_mean,
                        'ir': r_ir,
                    }

            factor_data = {
                'name': factor.name, 'alias': factor.alias,
                'ic_series': {'dates': dates, 'values': vals},
                'autocorr': autocorr,
                'products': [
                    {'name': p.name, 'desc': getattr(p, 'desc', p.name)}
                    for p in (factor.table.columns if factor.table is not None else [])
                    if p in tester.products and isinstance(p, Product)
                ],
            }
            # 附加衰减和滚动结果
            if ic_decay_results:
                factor_data['ic_decay'] = ic_decay_results.get(factor.alias, [])
            if rolling_ic:
                factor_data['rolling_ic'] = rolling_ic
            response['factors'].append(factor_data)

        # Merge into tester.factors
        existing = {f.alias for f in tester.factors}
        for f in factors:
            if f.alias not in existing:
                tester.factors.append(f); existing.add(f.alias)
            else:
                for i, ef in enumerate(tester.factors):
                    if ef.alias == f.alias:
                        tester.factors[i] = f; break

        return jsonify(response)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})
    finally:
        if _token is not None:
            _active_tester.reset(_token)
