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
        required = (['OPEN_ADJUSTED', 'HIGH_ADJUSTED', 'LOW_ADJUSTED', 'CLOSE_ADJUSTED', 'VOLUME'] if adjusted
                    else ['OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME'])
        raw_df = product.get_price_data(start_date, end_date, adjusted=adjusted)
        if raw_df is None or raw_df.empty:
            return jsonify({'error': '无价格数据'}), 404
        # 检测 OI 列
        _has_oi = 'OPEN_INTEREST' in raw_df.columns
        if _has_oi:
            required.append('OPEN_INTEREST')
        for col in required:
            if col not in raw_df.columns:
                return jsonify({'error': f'价格数据缺少列: {col}'}), 500
        if not isinstance(raw_df.index, pd.DatetimeIndex):
            raw_df.index = pd.to_datetime(raw_df.index.get_level_values(-1))
        if raw_df.index.tz is not None:
            raw_df.index = raw_df.index.tz_convert('UTC').tz_localize(None)

        # 构建区间：每个因子时间点作为右边界，左边界为上一个因子时间点（第一个左边界为数据开始）
        bins = factor_idx.union([raw_df.index.min()])  # 添加数据开始时间
        bins = bins.sort_values()
        # 使用 cut 将价格数据分到对应的区间（右闭？需要仔细）
        # 我们希望区间为 (left, right] 即包含右端点，左开右闭
        # 使用 pd.cut 的 right=True 参数
        labels = factor_idx  # 区间右端点作为标签
        # 将 raw_df 索引分到区间
        # 注意：pd.cut 要求 bins 严格递增，且 left 边界可能小于最小值，我们手动处理
        # 先创建区间索引
        intervals = pd.IntervalIndex.from_arrays(bins[:-1], bins[1:], closed='right')
        # 为每个价格时间点找到所属区间
        bin_indices = intervals.get_indexer(raw_df.index)
        # 过滤出属于有效区间的点（-1表示不在任何区间）
        mask = bin_indices >= 0
        raw_filtered = raw_df[mask]
        bin_indices = bin_indices[mask]

        # 分组聚合
        def agg_func(group):
            result = {
                'OPEN': group[required[0]].iloc[0],      # 区间内第一笔 open
                'HIGH': group[required[1]].max(),
                'LOW': group[required[2]].min(),
                'CLOSE': group[required[3]].iloc[-1],    # 区间内最后一笔 close
                'VOLUME': group[required[4]].sum(),       # 区间内总成交量
            }
            if _has_oi:
                result['OPEN_INTEREST'] = group['OPEN_INTEREST'].iloc[-1]  # 区间末持仓量
            return pd.Series(result)
        
        # 按 bin_indices 分组
        grouped = raw_filtered.groupby(bin_indices)
        ohlc = grouped.apply(agg_func).reindex(range(len(factor_idx)))
        ohlc = ohlc.replace({np.nan: None})
        # 将索引替换为因子时间点
        ohlc.index = factor_idx

        _is_daily = factor.freq is not None and factor.freq.is_day_multiple()
        if _is_daily:
            dates_out = [ts.strftime('%Y-%m-%d') for ts in factor_idx]
        else:
            dates_out = factor_dates
        result = {
            'dates': dates_out,
            'OPEN': ohlc['OPEN'].tolist(),
            'HIGH': ohlc['HIGH'].tolist(),
            'LOW': ohlc['LOW'].tolist(),
            'CLOSE': ohlc['CLOSE'].tolist(),
            'VOLUME': ohlc['VOLUME'].tolist(),
        }
        if _has_oi:
            result['OPEN_INTEREST'] = ohlc['OPEN_INTEREST'].tolist()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


@shared_bp.route('/get_factor_distribution', methods=['POST'])
def get_factor_distribution():
    """返回某个时间点所有品种的因子截面分布值。"""
    import pickle
    from pathlib import Path
    data = request.get_json()
    submission_id       = data.get('submission_id')
    factor_family_alias = data.get('factor_family_alias')
    factor_name         = data.get('factor_name')
    timestamp_ms        = data.get('timestamp')  # 毫秒时间戳
    product_name        = data.get('product')    # 当前选中产品名，用于高亮
    try:
        ts = pd.Timestamp(float(timestamp_ms) / 1000.0, unit='s', tz='Asia/Shanghai')
        with _factor_testers_lock:
            tester = next((t for t in shared.factor_testers if t.alias == str(submission_id)), None)
        if not tester:
            return jsonify({'error': '未找到测试器实例'}), 404
        factor_family = get_factor_family_instance(factor_family_alias)
        factors = factor_family.get_factors(params_list=_get_session_params(factor_family_alias, factor_family))
        target_factor = next((f for f in factors if f.name == factor_name), None)
        if not target_factor:
            return jsonify({'error': '未找到因子'}), 404

        cache_dir = Path('../data/cache/factor')
        cache_dir.mkdir(parents=True, exist_ok=True)
        scp_str = str(shared.start_calc_point).replace(':', '-').replace(' ', '_') if shared.start_calc_point else 'latest'
        cache = cache_dir / f"{target_factor.alias}_{scp_str}.pkl"

        table = None
        if cache.exists():
            with open(cache, 'rb') as f:
                table, scp_cache = pickle.load(f)
            if scp_cache != shared.start_calc_point:
                table = None
        if table is None:
            orig_products = tester.products.copy()
            try:
                target_factor.clear()
                tester.calc_factor(factors=target_factor)
                table = target_factor.table
            finally:
                tester.products = orig_products

        if table is None or table.empty:
            return jsonify({'error': '因子数据为空'}), 404

        idx = table.index.get_level_values(-1) if isinstance(table.index, pd.MultiIndex) else table.index
        tz = getattr(idx, 'tz', None)
        ts_compare = ts.tz_localize(tz) if tz and ts.tzinfo is None else (
            ts.replace(tzinfo=None) if not tz and ts.tzinfo else ts)
        diffs = np.abs(idx - ts_compare)
        nearest_i = diffs.argmin()
        nearest_diff = diffs[nearest_i]
        if nearest_diff > pd.Timedelta(days=2):
            return jsonify({'error': f'未找到 {ts_compare} 附近的因子数据，最近差 {nearest_diff}'}), 404

        row = table.iloc[nearest_i]
        actual_ts = idx[nearest_i]
        values = []
        for col, val in row.items():
            if isinstance(val, float) and (np.isnan(val) or np.isinf(val)):
                continue
            values.append({
                'product': str(getattr(col, 'name', col) if hasattr(col, 'name') else col),
                'value': float(val)
            })

        arr = np.array([v['value'] for v in values], dtype=float)
        n = len(arr)
        mean = float(np.mean(arr)) if n > 0 else None
        std  = float(np.std(arr, ddof=0)) if n > 1 else None
        mn   = float(np.min(arr))  if n > 0 else None
        mx   = float(np.max(arr))  if n > 0 else None
        skew = float(pd.Series(arr).skew()) if n > 2 else None
        kurt = float(pd.Series(arr).kurtosis()) if n > 3 else None
        pcts = {}
        for pct in [1, 5, 10, 25, 50, 75, 90, 95, 99]:
            pcts[str(pct)] = round(float(np.percentile(arr, pct)), 6) if n > 0 else None

        # 查找当前产品在该截面上的因子值
        highlight_value = None
        if product_name:
            for v in values:
                if str(v['product']) == str(product_name):
                    highlight_value = v['value']
                    break

        return jsonify({
            'success': True,
            'timestamp': int(actual_ts.timestamp() * 1000) if hasattr(actual_ts, 'timestamp') else timestamp_ms,
            'n': n,
            'stats': {'mean': mean, 'std': std, 'min': mn, 'max': mx, 'skewness': skew, 'kurtosis': kurt, 'percentiles': pcts},
            'values': sorted(values, key=lambda v: v['value']),
            'highlight_value': highlight_value,
            'highlight_product': product_name,
        })
    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500
