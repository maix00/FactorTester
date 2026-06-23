"""
Shared factor data-query routes (any test module can use):
  GET  /api/factor_list
  POST /get_factor_series
  POST /get_return_series
  POST /get_price_series
"""
from typing import Any
import numpy as np
import pandas as pd
import traceback
from flask import request, jsonify
from server.services.factor_registry import get_factor_family_instance
from server.services.page_runtime import get_factor_tester
import server.services.page_runtime as page_runtime
from server.services.session_runtime import current_user
from server.services.session_runtime import get_session_params
from tools.data.types import finest_index
from . import shared_bp
from server.services.api_response import api_fail, api_ok, route_guard
from .factor_data_helpers import (
    clip_series_by_tester_range,
    column_names as _column_names,
    find_tester_product,
    find_factor as _find_factor,
    match_product_column as _match_product_column,
    resolve_fe_table as _resolve_fe_table,
    resolve_product_from_tester,
    series_to_frontend,
)
from .price_data_helpers import to_epoch_ms
from .factor_tester_runtime import (
    create_factor_tester_for_product_path_selection,
)
from server.modules.single_factor_test.evaluation import FactorEvaluation
from tools.factors.tests.single_factor_test.factor_type_analysis.server_facade import (
    FactorTypeAnalysisRun,
)


def _request_page_uuid(data: dict) -> tuple[str | None, Any | None]:
    page_uuid = str(data.get('page_uuid') or '').strip()
    if not page_uuid:
        return None, (jsonify({'error': '缺少 page_uuid'}), 400)
    if page_runtime.get_page_owner(page_uuid) != current_user():
        return None, (jsonify({'error': 'page_uuid 不属于当前用户'}), 403)
    return page_uuid, None


def _request_product_path_selection_id(data: dict[str, Any]) -> str:
    raw = data.get("product_path_selection")
    if isinstance(raw, dict):
        selection_id = (
            raw.get("product_path_selection_id")
            or raw.get("selection_id")
            or raw.get("id")
            or data.get("product_path_selection_id")
        )
    else:
        selection_id = data.get("product_path_selection_id")
    selection_id = str(selection_id or "").strip()
    if not selection_id:
        raise AssertionError("缺少 product_path_selection_id")
    return selection_id


def _get_or_create_selection_tester(data: dict[str, Any], *, page_uuid: str, caller: str):
    selection_id = _request_product_path_selection_id(data)
    try:
        return get_factor_tester(selection_id, caller=caller, page_uuid=page_uuid)
    except AssertionError:
        return create_factor_tester_for_product_path_selection(
            data,
            selection_id,
            page_uuid=page_uuid,
        )


@shared_bp.route('/api/factor_evaluation/evaluate', methods=['POST'])
def factor_evaluation_evaluate():
    """Evaluate one factor for products selected directly from the product tree."""
    data = request.get_json() or {}
    page_uuid, error = _request_page_uuid(data)
    if error is not None:
        return error

    try:
        evaluation = FactorEvaluation.from_request(data, page_uuid=page_uuid)
        return jsonify(evaluation.run())
    except LookupError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc), "traceback": traceback.format_exc()}), 500


@shared_bp.route('/api/factor_type_analysis/analyze', methods=['POST'])
def factor_type_analysis_analyze():
    """
    因子类型分析 API。
    
    接收因子 + 产品 + 时间设置，返回：
      - 与各参照因子的相关性
      - 与各因子类别的聚合相关性
      - 最佳匹配类别
      - 品种间相关性矩阵
    """
    data = request.get_json() or {}
    page_uuid, error = _request_page_uuid(data)
    if error is not None:
        return error

    try:
        run = FactorTypeAnalysisRun.from_request(data, page_uuid=page_uuid)
        return jsonify(run.run())
    except LookupError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc), "traceback": traceback.format_exc()}), 500


@shared_bp.route('/api/factor_list')
@route_guard
def factor_list():
    factor_family_alias = request.args.get('factor_family_alias')
    if not factor_family_alias:
        return api_fail('缺少参数')
    page_uuid = request.args.get('page_uuid') or None
    owner_username = request.args.get('owner_username') or None
    ff = get_factor_family_instance(factor_family_alias, username=owner_username, page_uuid=page_uuid)
    params_list = get_session_params(factor_family_alias, ff)
    factors = ff.get_factors(params_list=params_list)
    # 构建 alias -> category 映射（从 session params 行中读取）
    alias_to_category = {}
    if isinstance(params_list, list):
        for row in params_list:
            if not isinstance(row, dict):
                continue
            cat = (row.get('category') or '').strip()
            if cat:
                try:
                    alias = ff.get_alias(**{k: v for k, v in row.items() if k != 'category'})
                    alias_to_category[alias] = cat
                except Exception:
                    continue
    factor_data = []
    for f in factors:
        factor_freq_param = f.family.params_dict.get('$F') if f.family else None
        factor_freq_value = factor_freq_param.get_value(f) if factor_freq_param is not None else None
        factor_freq_str = (
            factor_freq_param._value_space.alias(factor_freq_value)
            if factor_freq_param is not None and factor_freq_value is not None
            else ''
        )
        factor_freq = f.freq
        factor_freq_str2 = factor_freq.name if factor_freq is not None else ''
        factor_data.append({
            'alias': f.alias,
            'name': f.name,
            'default_return_freq': factor_freq_str,
            'freq': factor_freq_str2,
            'category': alias_to_category.get(f.alias, ''),
        })
    return api_ok({'factors': factor_data})


@shared_bp.route('/get_factor_series', methods=['POST'])
def get_factor_series():
    data = request.get_json()
    page_uuid, error = _request_page_uuid(data)
    if error is not None:
        return error
    factor_family_alias = data.get('factor_family_alias')
    factor_name         = data.get('factor_name')
    factor_alias        = data.get('factor_alias')
    product_name        = data.get('product')
    try:
        tester = _get_or_create_selection_tester(
            data, caller='get_factor_series', page_uuid=page_uuid
        )
        factor_family = get_factor_family_instance(factor_family_alias, page_uuid=page_uuid)
        factors = factor_family.get_factors(
            params_list=get_session_params(factor_family_alias, factor_family),
            page_uuid=page_uuid,
        )
        target_factor = _find_factor(factors, factor_name, factor_alias)
        if not target_factor:
            return jsonify({'error': '未找到因子'}), 404
        tester_factor = next((f for f in tester.factors if f.alias == target_factor.alias), target_factor)
        product = resolve_product_from_tester(tester, product_name)

        # 优先从 FactorRunResult.func_table 获取 FE intermediate（含 $Rev，无 SignalAlign）
        r = tester.results.get(tester_factor) if hasattr(tester, 'results') else None
        
        # DIAG: if not found, try matching by alias
        if r is None and hasattr(tester, 'results'):
            for k in tester.results:
                if getattr(k, 'alias', None) == target_factor.alias:
                    r = tester.results[k]
                    break
        
        fe_table = r.func_table if r is not None and not r.func_table.empty else pd.DataFrame()
        fe_col = _match_product_column(fe_table, product)

        series = None
        if fe_col is not None and not fe_table.empty:
            series = fe_table[fe_col].dropna()
        else:
            # 回退：用 FactorRunResult.table（含 SignalAlign，有 $Rev）
            factor_table = r.table if r is not None and not r.table.empty else pd.DataFrame()
            if factor_table.empty:
                factor_table = next(
                    (v.table for k, v in tester.results.items()
                     if isinstance(v.table, pd.DataFrame) and not v.table.empty
                     and getattr(k, 'alias', None) == target_factor.alias),
                    pd.DataFrame(),
                )
            fb_col = _match_product_column(factor_table, product)
            if fb_col is not None and not factor_table.empty:
                series = factor_table[fb_col].dropna()
            else:
                # 最后回退：调 factor.evaluate() 生成数据
                try:
                    tester_factor.evaluate(tester.products)
                    r2 = tester.results.get(tester_factor) if hasattr(tester, 'results') else None
                    fallback_table = r2.table if r2 is not None and not r2.table.empty else pd.DataFrame()
                    fb2_col = _match_product_column(fallback_table, product)
                    if fb2_col is not None and not fallback_table.empty:
                        series = fallback_table[fb2_col].dropna()
                except Exception:
                    pass
                if series is None:
                    available = _column_names(fe_table)[:10]
                    return jsonify({
                        'error': '未找到可用的因子截面数据，请先运行 IC 测试后再加载',
                        'available_products': available,
                    }), 400

        assert series is not None
        if series.empty:
            return jsonify({'error': '该产品在当前时间范围内无因子数据'}), 404

        series = clip_series_by_tester_range(series, tester)
        _daily = tester_factor.freq is not None and tester_factor.freq.is_day_multiple()
        dates_out, values = series_to_frontend(series, _daily)
        return jsonify({'dates': dates_out, 'values': values})
    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


@shared_bp.route('/get_return_series', methods=['POST'])
def get_return_series():
    data = request.get_json()
    page_uuid, error = _request_page_uuid(data)
    if error is not None:
        return error
    product_name        = data.get('product')
    factor_family_alias = data.get('factor_family_alias')
    factor_name         = data.get('factor_name')
    factor_alias        = data.get('factor_alias')
    try:
        tester = _get_or_create_selection_tester(
            data, caller='get_return_series', page_uuid=page_uuid
        )
        factor_family = get_factor_family_instance(factor_family_alias, page_uuid=page_uuid)
        factors = factor_family.get_factors(
            params_list=get_session_params(factor_family_alias, factor_family),
            page_uuid=page_uuid,
        )
        factor = _find_factor(factors, factor_name, factor_alias)
        if not factor:
            return jsonify({'error': '未找到因子'}), 404
        tester_factor = next((f for f in tester.factors if f.alias == factor.alias), factor)
        product = resolve_product_from_tester(tester, product_name)

        # 优先从 FactorRunResult.returns 获取 IC 测试阶段的 RE intermediate 数据
        r = tester.results.get(tester_factor) if hasattr(tester, 'results') else None
        if r is None and hasattr(tester, 'results'):
            for k in tester.results:
                if getattr(k, 'alias', None) == factor.alias:
                    r = tester.results[k]
                    break
        returns_table = r.returns if r is not None and not r.returns.empty else pd.DataFrame()
        if returns_table.empty:
            returns_table = next(
                (v.returns for k, v in tester.results.items()
                 if isinstance(v.returns, pd.DataFrame) and not v.returns.empty
                 and getattr(k, 'alias', None) == factor.alias),
                pd.DataFrame(),
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

        series = clip_series_by_tester_range(series, tester)
        _daily = tester_factor.freq is not None and tester_factor.freq.is_day_multiple()
        dates_out, values = series_to_frontend(series, _daily)
        return jsonify({'dates': dates_out, 'values': values})
    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


@shared_bp.route('/get_price_series', methods=['POST'])
def get_price_series():
    data = request.get_json()
    page_uuid, error = _request_page_uuid(data)
    if error is not None:
        return error
    product_name        = data.get('product')
    products_list       = data.get('products') or []
    primary_product     = data.get('primary_product')
    factor_dates        = data.get('factor_dates')
    adjusted            = data.get('adjusted', False)
    factor_family_alias = data.get('factor_family_alias')
    factor_name         = data.get('factor_name')
    factor_alias        = data.get('factor_alias')
    try:
        tester = _get_or_create_selection_tester(
            data, caller='get_price_series', page_uuid=page_uuid
        )
        factor_family = get_factor_family_instance(factor_family_alias, page_uuid=page_uuid)
        factors = factor_family.get_factors(
            params_list=get_session_params(factor_family_alias, factor_family),
            page_uuid=page_uuid,
        )
        factor = _find_factor(factors, factor_name, factor_alias)
        if not factor:
            return jsonify({'error': '未找到因子'}), 404
        product_names = []
        if isinstance(products_list, list):
            product_names = [str(x) for x in products_list if x not in (None, '')]
        if not product_names and product_name:
            product_names = [str(product_name)]
        if not product_names:
            return jsonify({'error': '未找到产品'}), 404

        primary_name = str(primary_product or product_names[0])

        assert factor_dates
        if isinstance(factor_dates, list) and factor_dates and isinstance(factor_dates[0], str):
            factor_idx = pd.to_datetime(factor_dates)
        else:
            factor_idx = pd.to_datetime(factor_dates, unit='ms')
        start_date = factor_idx.min().strftime('%Y-%m-%d')
        end_date   = factor_idx.max().strftime('%Y-%m-%d')
        required = (['OPEN_ADJUSTED', 'HIGH_ADJUSTED', 'LOW_ADJUSTED', 'CLOSE_ADJUSTED', 'VOLUME'] if adjusted
                    else ['OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME'])
        def _build_series_for_product(product):
            raw_df = product.get_price_data(start_date, end_date, adjusted=adjusted)
            if raw_df is None or raw_df.empty:
                return None
            has_oi = 'OPEN_INTEREST' in raw_df.columns
            required_cols = list(required)
            if has_oi:
                required_cols.append('OPEN_INTEREST')
            for col in required_cols:
                if col not in raw_df.columns:
                    return None
            if not isinstance(raw_df.index, pd.DatetimeIndex):
                raw_df.index = pd.to_datetime(finest_index(raw_df.index))
            if raw_df.index.tz is not None:
                raw_df.index = raw_df.index.tz_convert('UTC').tz_localize(None)

            bins = factor_idx.union([raw_df.index.min()]).sort_values()
            intervals = pd.IntervalIndex.from_arrays(bins[:-1], bins[1:], closed='right')
            bin_indices = intervals.get_indexer(raw_df.index)
            mask = bin_indices >= 0
            raw_filtered = raw_df[mask]
            bin_indices2 = bin_indices[mask]

            def agg_func(group):
                res = {
                    'OPEN': group[required_cols[0]].iloc[0],
                    'HIGH': group[required_cols[1]].max(),
                    'LOW': group[required_cols[2]].min(),
                    'CLOSE': group[required_cols[3]].iloc[-1],
                    'VOLUME': group[required_cols[4]].sum(),
                }
                if has_oi:
                    res['OPEN_INTEREST'] = group['OPEN_INTEREST'].iloc[-1]
                return pd.Series(res)

            grouped = raw_filtered.groupby(bin_indices2)
            ohlc = grouped.apply(agg_func).reindex(range(len(factor_idx))).replace({np.nan: None})
            ohlc.index = factor_idx
            out = {
                'product': getattr(product, 'name', str(product)),
                'OPEN': ohlc['OPEN'].tolist(),
                'HIGH': ohlc['HIGH'].tolist(),
                'LOW': ohlc['LOW'].tolist(),
                'CLOSE': ohlc['CLOSE'].tolist(),
                'VOLUME': ohlc['VOLUME'].tolist(),
            }
            if has_oi:
                out['OPEN_INTEREST'] = ohlc['OPEN_INTEREST'].tolist()
            return out

        series_list = []
        for name in product_names:
            p = find_tester_product(tester, name)
            if p is None:
                continue
            s = _build_series_for_product(p)
            if s is not None:
                series_list.append(s)

        if not series_list:
            return jsonify({'error': '无价格数据'}), 404

        primary_series = next((s for s in series_list if s.get('product') == primary_name), series_list[0])

        _is_daily = factor.freq is not None and factor.freq.is_day_multiple()
        if _is_daily:
            dates_out = [ts.strftime('%Y-%m-%d') for ts in factor_idx]
        else:
            dates_out = factor_dates
        result = {
            'dates': dates_out,
            'OPEN': primary_series['OPEN'],
            'HIGH': primary_series['HIGH'],
            'LOW': primary_series['LOW'],
            'CLOSE': primary_series['CLOSE'],
            'VOLUME': primary_series['VOLUME'],
            'series_list': series_list,
        }
        if 'OPEN_INTEREST' in primary_series:
            result['OPEN_INTEREST'] = primary_series['OPEN_INTEREST']
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


@shared_bp.route('/get_factor_distribution', methods=['POST'])
def get_factor_distribution():
    """返回某个时间点所有品种的因子截面分布值。"""
    data = request.get_json()
    page_uuid, error = _request_page_uuid(data)
    if error is not None:
        return error
    factor_family_alias = data.get('factor_family_alias')
    factor_name         = data.get('factor_name')
    factor_alias        = data.get('factor_alias')
    timestamp_ms        = data.get('timestamp')  # 毫秒时间戳
    product_name        = data.get('product')    # 当前选中产品名，用于高亮
    try:
        ts = pd.Timestamp(float(timestamp_ms) / 1000.0, unit='s', tz='Asia/Shanghai')
        tester = _get_or_create_selection_tester(
            data, caller='get_factor_distribution', page_uuid=page_uuid
        )
        factor_family = get_factor_family_instance(factor_family_alias, page_uuid=page_uuid)
        factors = factor_family.get_factors(
            params_list=get_session_params(factor_family_alias, factor_family),
            page_uuid=page_uuid,
        )
        target_factor = _find_factor(factors, factor_name, factor_alias)
        if not target_factor:
            return jsonify({'error': '未找到因子'}), 404

        tester_factor = next((f for f in tester.factors if f.alias == target_factor.alias), target_factor)
        table = _resolve_fe_table(tester_factor, tester)
        if not isinstance(table, pd.DataFrame) or table.empty:
            # fallback: 尝试调 factor.evaluate()
            try:
                tester_factor.evaluate(tester.products)
                r = tester.results.get(tester_factor) if hasattr(tester, 'results') else None
                if r is not None and not r.table.empty:
                    table = r.table
            except Exception:
                pass
        if not isinstance(table, pd.DataFrame) or table.empty:
            return jsonify({'error': '未找到可用的因子截面数据，请先运行 IC 测试后再查看分布'}), 400

        idx = finest_index(table.index) if isinstance(table.index, pd.MultiIndex) else table.index
        tz = getattr(idx, 'tz', None)
        ts_compare = ts.tz_localize(tz) if tz and ts.tzinfo is None else (
            ts.replace(tzinfo=None) if not tz and ts.tzinfo else ts)
        diffs = np.abs(idx - ts_compare)  # type: ignore[operator]
        nearest_i = diffs.argmin()
        nearest_diff = diffs[nearest_i]
        if nearest_diff > pd.Timedelta(days=2):
            return jsonify({'error': f'未找到 {ts_compare} 附近的因子数据，最近差 {nearest_diff}'}), 404

        row = table.iloc[nearest_i]
        actual_ts: Any = idx[int(nearest_i)]
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
            'timestamp': to_epoch_ms(actual_ts, use_utc=True) if hasattr(actual_ts, 'timestamp') else timestamp_ms,
            'n': n,
            'stats': {'mean': mean, 'std': std, 'min': mn, 'max': mx, 'skewness': skew, 'kurtosis': kurt, 'percentiles': pcts},
            'values': sorted(values, key=lambda v: v['value']),
            'highlight_value': highlight_value,
            'highlight_product': product_name,
        })
    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500
