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
from types import SimpleNamespace
from flask import request, jsonify
from server.shared import get_factor_family_instance, _get_session_params, _factor_testers_lock
import server.shared as shared
from . import shared_bp


def _match_product_column(table: pd.DataFrame | None, product) -> object | None:
    """在表格列中匹配产品对象，兼容列为 Product 或字符串名称。"""
    if not isinstance(table, pd.DataFrame) or table.empty:
        return None
    if product in table.columns:
        return product
    target_name = getattr(product, 'name', str(product))
    target_alias = getattr(product, 'alias', target_name)
    for col in table.columns:
        col_name = getattr(col, 'name', str(col))
        col_alias = getattr(col, 'alias', col_name)
        if str(col_name) == str(target_name) or str(col_alias) == str(target_alias):
            return col
    return None


def _column_names(table: pd.DataFrame | None) -> list[str]:
    if not isinstance(table, pd.DataFrame) or table.empty:
        return []
    return [str(getattr(c, 'name', c)) for c in table.columns]


def _find_factor(factors, factor_name: str | None, factor_alias: str | None):
    if factor_alias not in (None, ''):
        by_alias = next((f for f in factors if f.alias == factor_alias), None)
        if by_alias is not None:
            return by_alias
    if factor_name not in (None, ''):
        return next((f for f in factors if f.name == factor_name or f.alias == factor_name), None)
    return None


def _is_neg_expr(expr) -> bool:
    op = getattr(expr, 'op', None)
    operands = getattr(expr, 'operands', ())
    return op == 'neg' and hasattr(operands, '__len__') and len(operands) == 1


def _resolve_fe_table(tester_factor) -> pd.DataFrame | None:
    """解析 IC 因子值表（含 Neg 语义），优先级：_ic_fe_intermediate > FactorData(_func_expr) > source_table(+Neg 补偿)。"""
    fe_table = getattr(tester_factor, '_ic_fe_intermediate', None)
    if isinstance(fe_table, pd.DataFrame) and not fe_table.empty:
        return fe_table

    func_expr = getattr(tester_factor, '_func_expr', None)
    if func_expr is not None:
        try:
            from tools.factors.FactorData import FactorData
            fd = FactorData.get_by_hash(str(func_expr._structural_key()))
            if fd is not None and isinstance(fd.source_table, pd.DataFrame) and not fd.source_table.empty:
                return fd.source_table
        except Exception:
            pass

    src = getattr(tester_factor, 'source_table', None)
    if isinstance(src, pd.DataFrame) and not src.empty:
        # Factor.source_table 在外层是 neg(SignalAlign(...)) 时通常是未取反的 raw_data，这里补上符号。
        return -src if _is_neg_expr(func_expr) else src
    return None


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
            factor_freq_param = f.family.params_dict.get('$F') if f.family else None
            factor_freq_value = factor_freq_param.get_value(f) if factor_freq_param is not None else None
            factor_freq_str = (
                factor_freq_param._value_space.alias(factor_freq_value)
                if factor_freq_param is not None and factor_freq_value is not None
                else ''
            )
            factor_data.append({'alias': f.alias, 'name': f.name, 'default_return_freq': factor_freq_str})
        return jsonify({'success': True, 'factors': factor_data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@shared_bp.route('/get_factor_series', methods=['POST'])
def get_factor_series():
    data = request.get_json()
    submission_id       = data.get('submission_id')
    factor_family_alias = data.get('factor_family_alias')
    factor_name         = data.get('factor_name')
    factor_alias        = data.get('factor_alias')
    product_name        = data.get('product')
    try:
        with _factor_testers_lock:
            target_suffix = f":{submission_id}"
            tester = next((t for t in shared.factor_testers if t.alias == str(submission_id) or t.alias.endswith(target_suffix)), None)
        if not tester:
            return jsonify({'error': '未找到测试器实例'}), 404
        factor_family = get_factor_family_instance(factor_family_alias)
        factors = factor_family.get_factors(params_list=_get_session_params(factor_family_alias, factor_family))
        target_factor = _find_factor(factors, factor_name, factor_alias)
        if not target_factor:
            return jsonify({'error': '未找到因子'}), 404
        tester_factor = next((f for f in tester.factors if f.alias == target_factor.alias), target_factor)
        product = next((p for p in tester.products if p.name == product_name), None)
        if not product:
            product = SimpleNamespace(name=product_name, alias=product_name)

        # 优先使用 IC 测试阶段的 FE intermediate；若缺失，则按 _func_expr/source_table 回退并保持 Neg 语义。
        fe_table = _resolve_fe_table(tester_factor)
        fe_col = _match_product_column(fe_table, product)

        series = None
        if fe_col is not None and isinstance(fe_table, pd.DataFrame):
            series = fe_table[fe_col].dropna()
        else:
            factor_table = tester.factor_tables.get(tester_factor)
            if factor_table is None:
                factor_table = next(
                    (v for k, v in tester.factor_tables.items() if getattr(k, 'alias', None) == target_factor.alias),
                    None,
                )
            fb_col = _match_product_column(factor_table, product)
            if fb_col is not None and isinstance(factor_table, pd.DataFrame):
                series = factor_table[fb_col].dropna()
            else:
                available = _column_names(fe_table)[:10]
                return jsonify({
                    'error': '未找到可用的因子截面数据，请先运行 IC 测试后再加载',
                    'available_products': available,
                }), 400

        assert series is not None
        if series.empty:
            return jsonify({'error': '该产品在当前时间范围内无因子数据'}), 404

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
        _daily = tester_factor.freq is not None and tester_factor.freq.is_day_multiple()
        dates_out = ([ts.strftime('%Y-%m-%d') for ts in idx] if _daily
                     else (idx.view(np.int64) // 10**6).tolist())
        values = [None if (isinstance(v, float) and (pd.isna(v) or np.isinf(v))) else v
                  for v in series.values.tolist()]
        return jsonify({'dates': dates_out, 'values': values})
    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


@shared_bp.route('/get_return_series', methods=['POST'])
def get_return_series():
    data = request.get_json()
    submission_id       = data.get('submission_id')
    product_name        = data.get('product')
    factor_family_alias = data.get('factor_family_alias')
    factor_name         = data.get('factor_name')
    factor_alias        = data.get('factor_alias')
    try:
        with _factor_testers_lock:
            target_suffix = f":{submission_id}"
            tester = next((t for t in shared.factor_testers if t.alias == str(submission_id) or t.alias.endswith(target_suffix)), None)
        if not tester:
            return jsonify({'error': '未找到测试器实例'}), 404
        factor_family = get_factor_family_instance(factor_family_alias)
        factors = factor_family.get_factors(params_list=_get_session_params(factor_family_alias, factor_family))
        factor = _find_factor(factors, factor_name, factor_alias)
        if not factor:
            return jsonify({'error': '未找到因子'}), 404
        tester_factor = next((f for f in tester.factors if f.alias == factor.alias), factor)
        product = next((p for p in tester.products if p.name == product_name), None)
        if not product:
            product = SimpleNamespace(name=product_name, alias=product_name)

        # 优先使用 IC 测试阶段由 intermediate(RE) 回填的数据
        returns_table = tester.factor_returns.get(tester_factor)
        if returns_table is None:
            returns_table = next(
                (v for k, v in tester.factor_returns.items() if getattr(k, 'alias', None) == factor.alias),
                None,
            )
        ret_col = _match_product_column(returns_table, product)
        if ret_col is not None and isinstance(returns_table, pd.DataFrame):
            series = returns_table[ret_col].dropna()
        else:
            available = _column_names(returns_table)[:10]
            return jsonify({
                'error': '未找到可用的收益率数据，请先运行 IC 测试后再加载',
                'available_products': available,
            }), 400
        if series.empty:
            return jsonify({'error': '该产品在当前时间范围内无收益率数据'}), 404

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
        _daily = tester_factor.freq is not None and tester_factor.freq.is_day_multiple()
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
    factor_alias        = data.get('factor_alias')
    try:
        with _factor_testers_lock:
            tester = next((t for t in shared.factor_testers if t.alias == str(submission_id)), None)
        if not tester:
            return jsonify({'error': '未找到测试器实例'}), 404
        factor_family = get_factor_family_instance(factor_family_alias)
        factors = factor_family.get_factors(params_list=_get_session_params(factor_family_alias, factor_family))
        factor = _find_factor(factors, factor_name, factor_alias)
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
    data = request.get_json()
    submission_id       = data.get('submission_id')
    factor_family_alias = data.get('factor_family_alias')
    factor_name         = data.get('factor_name')
    factor_alias        = data.get('factor_alias')
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
        target_factor = _find_factor(factors, factor_name, factor_alias)
        if not target_factor:
            return jsonify({'error': '未找到因子'}), 404

        tester_factor = next((f for f in tester.factors if f.alias == target_factor.alias), target_factor)
        table = _resolve_fe_table(tester_factor)
        if not isinstance(table, pd.DataFrame) or table.empty:
            return jsonify({'error': '未找到可用的因子截面数据，请先运行 IC 测试后再查看分布'}), 400

        idx = table.index.get_level_values(-1) if isinstance(table.index, pd.MultiIndex) else table.index
        tz = getattr(idx, 'tz', None)
        ts_compare = ts.tz_localize(tz) if tz and ts.tzinfo is None else (
            ts.replace(tzinfo=None) if not tz and ts.tzinfo else ts)
        diffs = np.abs(idx - ts_compare)  # type: ignore[operator]
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
        skew = float(pd.Series(arr).skew()) if n > 2 else None  # type: ignore[arg-type]
        kurt = float(pd.Series(arr).kurtosis()) if n > 3 else None  # type: ignore[arg-type]
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
            'timestamp': int(actual_ts.timestamp() * 1000) if hasattr(actual_ts, 'timestamp') else timestamp_ms,  # type: ignore[union-attr]
            'n': n,
            'stats': {'mean': mean, 'std': std, 'min': mn, 'max': mx, 'skewness': skew, 'kurtosis': kurt, 'percentiles': pcts},
            'values': sorted(values, key=lambda v: v['value']),
            'highlight_value': highlight_value,
            'highlight_product': product_name,
        })
    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500
