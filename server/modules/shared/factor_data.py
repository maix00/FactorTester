"""
Shared factor data-query routes (any test module can use):
  GET  /api/factor_list
  POST /get_factor_series
  POST /get_return_series
  POST /get_price_series
"""
import numpy as np
import pandas as pd
import traceback
from flask import request, jsonify
from server.shared import get_factor_family_instance, _get_session_params, _factor_testers_lock
import server.shared as shared
from . import shared_bp


@shared_bp.route('/api/factor_list')
def factor_list():
    factor_family_alias = request.args.get('factor_family_alias')
    if not factor_family_alias:
        return jsonify({'success': False, 'error': '缺少参数'})
    try:
        ff = get_factor_family_instance(factor_family_alias)
        factors = ff.get_factors(params_list=_get_session_params(factor_family_alias, ff))
        factor_data = []
        for f in factors:
            factor_freq_param = f.params_dict.get('$F')
            factor_freq_value = factor_freq_param.get_value(f) if factor_freq_param is not None else None
            factor_freq_str = (
                factor_freq_param.get_value_alias(factor_freq_value)
                if factor_freq_param is not None and factor_freq_value is not None
                else ''
            )
            factor_data.append({'alias': f.alias, 'name': f.name, 'default_return_freq': factor_freq_str})
        return jsonify({'success': True, 'factors': factor_data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@shared_bp.route('/get_factor_series', methods=['POST'])
def get_factor_series():
    import pickle
    from pathlib import Path
    data = request.get_json()
    submission_id       = data.get('submission_id')
    factor_family_alias = data.get('factor_family_alias')
    factor_name         = data.get('factor_name')
    product_name        = data.get('product')
    re_calc             = data.get('re_calc', False)
    try:
        with _factor_testers_lock:
            tester = next((t for t in shared.factor_testers if t.alias == str(submission_id)), None)
        if not tester:
            return jsonify({'error': '未找到测试器实例'}), 404
        factor_family = get_factor_family_instance(factor_family_alias)
        factors = factor_family.get_factors(params_list=_get_session_params(factor_family_alias, factor_family))
        target_factor = next((f for f in factors if f.name == factor_name), None)
        if not target_factor:
            return jsonify({'error': '未找到因子'}), 404
        product = next((p for p in tester.products if p.name == product_name), None)
        if not product:
            return jsonify({'error': '未找到产品'}), 404

        cache_dir = Path('../data/cache/factor')
        cache_dir.mkdir(parents=True, exist_ok=True)
        scp_str = str(shared.start_calc_point).replace(':', '-').replace(' ', '_') if shared.start_calc_point else 'latest'
        cache1 = cache_dir / f"{target_factor.alias}_{scp_str}.pkl"
        cache2 = cache_dir / f"{target_factor.alias}_{product.alias}_{scp_str}.pkl"

        series = None
        if not re_calc and cache1.exists():
            with open(cache1, 'rb') as f:
                table, scp_cache = pickle.load(f)
            if product in table.columns and scp_cache == shared.start_calc_point:
                series = table[product].dropna()
            else:
                re_calc = True
        elif not re_calc and cache2.exists():
            with open(cache2, 'rb') as f:
                table, scp_cache = pickle.load(f)
            if scp_cache == shared.start_calc_point:
                series = (table[product].dropna() if hasattr(table, 'columns') and product in table.columns
                          else table.dropna())
            else:
                re_calc = True
        if re_calc or series is None:
            orig = tester.products.copy()
            tester.products = [product]
            target_factor.clear()
            try:
                tester.calc_factor(factors=target_factor)
                if target_factor.table is None or target_factor.table.empty:
                    raise ValueError("因子计算无结果")
                series = target_factor.table[product].dropna()
                with open(cache2, 'wb') as f:
                    pickle.dump((target_factor.table, shared.start_calc_point), f)
            finally:
                tester.products = orig

        assert series is not None

        def _get_idx(s):
            return s.index.get_level_values(-1) if isinstance(s.index, pd.MultiIndex) else s.index

        def _loc(ts, idx):
            tz = getattr(idx, 'tz', None)
            return ts.tz_localize(tz) if tz and ts.tzinfo is None else (
                ts.replace(tzinfo=None) if not tz and ts.tzinfo else ts)

        idx = _get_idx(series)
        if tester.start_date is not None:
            series = series[idx >= _loc(pd.Timestamp(tester.start_date), idx)]
            idx = _get_idx(series)
        if tester.end_date is not None:
            series = series[idx <= _loc(pd.Timestamp(tester.end_date), idx)]
        idx = _get_idx(series)
        _daily = target_factor.freq is not None and target_factor.freq.is_day_multiple()
        dates_out = ([ts.strftime('%Y-%m-%d') for ts in idx] if _daily
                     else (idx.view(np.int64) // 10**6).tolist())
        values = [None if (isinstance(v, float) and (pd.isna(v) or np.isinf(v))) else v
                  for v in series.values.tolist()]
        return jsonify({'dates': dates_out, 'values': values})
    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


@shared_bp.route('/get_return_series', methods=['POST'])
def get_return_series():
    import pickle, hashlib
    from pathlib import Path
    data = request.get_json()
    submission_id       = data.get('submission_id')
    product_name        = data.get('product')
    factor_family_alias = data.get('factor_family_alias')
    factor_name         = data.get('factor_name')
    return_freq         = data.get('return_freq', None)
    paths               = data.get('paths', [])
    re_calc             = data.get('re_calc', False)
    try:
        with _factor_testers_lock:
            tester = next((t for t in shared.factor_testers if t.alias == str(submission_id)), None)
        if not tester:
            return jsonify({'error': '未找到测试器实例'}), 404
        factor_family = get_factor_family_instance(factor_family_alias)
        factors = factor_family.get_factors(params_list=_get_session_params(factor_family_alias, factor_family))
        factor = next((f for f in factors if f.name == factor_name), None)
        if not factor:
            return jsonify({'error': '未找到因子'}), 404
        product = next((p for p in tester.products if p.name == product_name), None)
        if not product:
            return jsonify({'error': '未找到产品'}), 404

        cache_ic  = Path('../data/cache/ic')
        cache_ret = Path('../data/cache/return')
        cache_ret.mkdir(parents=True, exist_ok=True)
        start_str = str(tester.start_date).replace(':', '-').replace(' ', '_')
        end_str   = str(tester.end_date).replace(':', '-').replace(' ', '_')
        ph = hashlib.md5(str(sorted(paths)).encode()).hexdigest()
        c1 = cache_ic  / f"{ph}_{factor.alias}_{return_freq}_{start_str}_{end_str}.pkl"
        c2 = cache_ret / f"{product.alias}_{return_freq}_{start_str}_{end_str}.pkl"

        series = None
        if not re_calc and c1.exists():
            with open(c1, 'rb') as f:
                _, _, _, rf_c, returns_table, sd_c, ed_c = pickle.load(f)
            if rf_c == return_freq and sd_c == tester.start_date and ed_c == tester.end_date:
                series = returns_table[product].dropna()
            else:
                re_calc = True
        elif not re_calc and c2.exists():
            with open(c2, 'rb') as f:
                returns_table, rf_c, sd_c, ed_c = pickle.load(f)
            if rf_c == return_freq and sd_c == tester.start_date and ed_c == tester.end_date:
                series = (returns_table[product].dropna()
                          if hasattr(returns_table, 'columns') and product in returns_table.columns
                          else returns_table.dropna())
            else:
                re_calc = True
        if re_calc or series is None:
            factor.clear()
            factor.products = set([product])
            returns_df = factor.calc_returns(return_freq=(None if return_freq == 'N' else return_freq))
            series = (returns_df[product].dropna()
                      if isinstance(returns_df, pd.DataFrame) and product in returns_df.columns
                      else (returns_df.iloc[:, 0].dropna()
                            if isinstance(returns_df, pd.DataFrame) else returns_df.dropna()))
            with open(c2, 'wb') as f:
                pickle.dump((series, return_freq, tester.start_date, tester.end_date), f)

        def _get_idx(s):
            return s.index.get_level_values(-1) if isinstance(s.index, pd.MultiIndex) else s.index

        def _loc(ts, idx):
            tz = getattr(idx, 'tz', None)
            return ts.tz_localize(tz) if tz and ts.tzinfo is None else (
                ts.replace(tzinfo=None) if not tz and ts.tzinfo else ts)

        idx = _get_idx(series)
        if tester.start_date is not None:
            series = series[idx >= _loc(pd.Timestamp(tester.start_date), idx)]
            idx = _get_idx(series)
        if tester.end_date is not None:
            series = series[idx <= _loc(pd.Timestamp(tester.end_date), idx)]
        idx = _get_idx(series)
        _daily = factor.freq is not None and factor.freq.is_day_multiple()
        dates_out = ([ts.strftime('%Y-%m-%d') for ts in idx] if _daily
                     else (idx.view(np.int64) // 10**6).tolist())
        values = [None if (isinstance(v, float) and (pd.isna(v) or np.isinf(v))) else v
                  for v in series.values.tolist()]
        return jsonify({'dates': dates_out, 'values': values})
    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


@shared_bp.route('/get_price_series', methods=['POST'])
def get_price_series():
    data = request.get_json()
    submission_id       = data.get('submission_id')
    product_name        = data.get('product')
    factor_dates        = data.get('factor_dates')
    adjusted            = data.get('adjusted', False)
    factor_family_alias = data.get('factor_family_alias')
    factor_name         = data.get('factor_name')
    try:
        with _factor_testers_lock:
            tester = next((t for t in shared.factor_testers if t.alias == str(submission_id)), None)
        if not tester:
            return jsonify({'error': '未找到测试器实例'}), 404
        factor_family = get_factor_family_instance(factor_family_alias)
        factors = factor_family.get_factors(params_list=_get_session_params(factor_family_alias, factor_family))
        factor = next((f for f in factors if f.name == factor_name), None)
        if not factor:
            return jsonify({'error': '未找到因子'}), 404
        product = next((p for p in tester.products if p.name == product_name), None)
        if not product:
            return jsonify({'error': '未找到产品'}), 404

        assert factor_dates
        factor_idx = pd.to_datetime(factor_dates, unit='ms')
        start_date = factor_idx.min().strftime('%Y-%m-%d')
        end_date   = factor_idx.max().strftime('%Y-%m-%d')
        required = (['OPEN_ADJUSTED', 'HIGH_ADJUSTED', 'LOW_ADJUSTED', 'CLOSE_ADJUSTED'] if adjusted
                    else ['OPEN', 'HIGH', 'LOW', 'CLOSE'])
        raw_df = product.get_price_data(start_date, end_date, adjusted=adjusted)
        if raw_df is None or raw_df.empty:
            return jsonify({'error': '无价格数据'}), 404
        for col in required:
            if col not in raw_df.columns:
                return jsonify({'error': f'价格数据缺少列: {col}'}), 500
        if not isinstance(raw_df.index, pd.DatetimeIndex):
            raw_df.index = pd.to_datetime(raw_df.index.get_level_values(-1))
        if raw_df.index.tz is not None:
            raw_df.index = raw_df.index.tz_convert('UTC').tz_localize(None)

        bins = factor_idx.union([raw_df.index.min()]).sort_values()
        intervals = pd.IntervalIndex.from_arrays(bins[:-1], bins[1:], closed='right')
        bin_indices = intervals.get_indexer(raw_df.index)
        mask = bin_indices >= 0
        raw_filtered = raw_df[mask]
        bin_indices  = bin_indices[mask]

        def agg_func(group):
            return pd.Series({
                'OPEN':  group[required[0]].iloc[0],
                'HIGH':  group[required[1]].max(),
                'LOW':   group[required[2]].min(),
                'CLOSE': group[required[3]].iloc[-1],
            })

        ohlc = raw_filtered.groupby(bin_indices).apply(agg_func).reindex(range(len(factor_idx)))
        ohlc = ohlc.replace({np.nan: None})
        ohlc.index = factor_idx
        _daily = factor.freq is not None and factor.freq.is_day_multiple()
        dates_out = [ts.strftime('%Y-%m-%d') for ts in factor_idx] if _daily else factor_dates
        return jsonify({
            'dates': dates_out,
            'OPEN':  ohlc['OPEN'].tolist(),
            'HIGH':  ohlc['HIGH'].tolist(),
            'LOW':   ohlc['LOW'].tolist(),
            'CLOSE': ohlc['CLOSE'].tolist(),
        })
    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500
