"""
价格序列查看 API
  GET  /api/list_product_names  — 获取所有可查看价格的品种名称列表
  GET  /api/product_tree        — 获取产品类别树（复用 CategoryTree，支持多产品类型）
  POST /api/get_price_data      — 获取指定品种的价格序列（复权/非复权）
"""
import traceback
import numpy as np
import pandas as pd
from flask import request, jsonify
from . import shared_bp
from Settings import get_all_products, get_cat_tree
from server.shared import convert_to_fancytree


@shared_bp.route('/api/list_product_names')
def list_product_names():
    """返回所有品种的中英文名称列表。"""
    try:
        products = get_all_products()
        result = []
        for p in products:
            if p is None:
                continue
            name = getattr(p, 'name', None) or getattr(p, 'alias', None) or str(p)
            desc = getattr(p, 'desc', None) or name
            code = getattr(p, 'code', None)
            result.append({
                'name': name,
                'desc': desc,
                'code': code or name.split('.')[0] if '.' in name else name,
                'exchange': name.split('.')[1] if '.' in name and '@' not in name.split('.')[1] else name.split('.')[1].split('@')[0] if '.' in name else '',
            })
        return jsonify({'success': True, 'products': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()}), 500


@shared_bp.route('/api/product_tree')
def get_product_tree():
    """返回产品类别树（Fancytree 格式），支持所有产品类型。"""
    try:
        cat_tree = get_cat_tree()
        fancytree_data = convert_to_fancytree(cat_tree.tree, checkbox_default=False)
        return jsonify(fancytree_data)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()}), 500


@shared_bp.route('/api/get_price_data', methods=['POST'])
def get_price_data():
    """
    获取指定品种的价格序列。

    请求参数：
        product_name : 品种名称（如 'IF.CFE'）
        adjusted     : 是否复权 (默认 false)
        freq         : 数据频率 'DAY1' | 'MIN1' (默认 'DAY1')
        start_date   : 开始日期 'YYYY-MM-DD' (可选)
        end_date     : 结束日期 'YYYY-MM-DD' (可选)

    返回：
        {
            success: true,
            product: 'IF.CFE',
            adjusted: false,
            freq: 'DAY1',
            data: [{ time: '2024-01-02', open: ..., high: ..., low: ..., close: ..., volume: ... }, ...]
        }
    """
    data = request.get_json()
    product_name = data.get('product_name')
    adjusted = data.get('adjusted', False)
    freq_str = data.get('freq', 'DAY1')
    start_date = data.get('start_date')
    end_date = data.get('end_date')

    if not product_name:
        return jsonify({'success': False, 'error': '缺少 product_name'}), 400

    try:
        products = get_all_products()
        product = next((p for p in products if p is not None and (
            getattr(p, 'name', None) == product_name or
            getattr(p, 'alias', None) == product_name
        )), None)

        if not product:
            return jsonify({'success': False, 'error': f'未找到品种: {product_name}'}), 404

        from tools.data.DataFreq import DataFreq
        try:
            freq = DataFreq(freq_str)
        except Exception:
            freq = DataFreq('DAY1')

        # 设置频率
        old_freq = getattr(product, 'current_freq', None)
        try:
            product.set_current_freq(freq)
        except ValueError:
            # 回退到默认
            available = product.list_available_freqs()
            if not available:
                return jsonify({'success': False, 'error': '无可用数据频率'}), 400
            freq = available[0]
            product.set_current_freq(freq)

        # 确定日期范围
        if start_date:
            start = pd.Timestamp(start_date)
        else:
            start = pd.Timestamp('2000-01-01')
        if end_date:
            end = pd.Timestamp(end_date)
        else:
            end = pd.Timestamp.now()

        # 获取价格数据
        price_df = product.get_price_data(start, end, adjusted=adjusted)

        if price_df is None or price_df.empty:
            return jsonify({'success': False, 'error': '指定范围内无价格数据'}), 404

        # 还原索引
        if not isinstance(price_df.index, pd.DatetimeIndex):
            price_df.index = pd.to_datetime(price_df.index.get_level_values(-1))

        # 如果有时区，转为 UTC 后去时区
        if getattr(price_df.index, 'tz', None) is not None:
            price_df.index = price_df.index.tz_convert('UTC').tz_localize(None)

        # 提取 OHLCV + 可选 OI 列
        if adjusted:
            o_col, h_col, l_col, c_col, v_col = (
                'OPEN_ADJUSTED', 'HIGH_ADJUSTED', 'LOW_ADJUSTED', 'CLOSE_ADJUSTED', 'VOLUME'
            )
        else:
            o_col, h_col, l_col, c_col, v_col = (
                'OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME'
            )
        # 检测 OI 列
        oi_col = 'OPEN_INTEREST' if 'OPEN_INTEREST' in price_df.columns else None
        has_oi = oi_col is not None

        freq_is_daily = freq.is_day_multiple()

        result_data = []
        for idx, row in price_df.iterrows():
            ts_val = idx
            if hasattr(ts_val, 'strftime'):
                time_str = ts_val.strftime('%Y-%m-%d' if freq_is_daily else '%Y-%m-%d %H:%M:%S')
                timestamp_ms = int(ts_val.timestamp() * 1000)
            else:
                time_str = str(ts_val)
                timestamp_ms = int(pd.Timestamp(ts_val).timestamp() * 1000)

            entry = {
                'time': time_str,
                'timestamp': timestamp_ms,
            }

            def _val(col, dflt=None):
                v = row.get(col)
                if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
                    return dflt
                return float(v)

            entry['open']   = _val(o_col)
            entry['high']   = _val(h_col)
            entry['low']    = _val(l_col)
            entry['close']  = _val(c_col)
            entry['volume'] = _val(v_col, 0)
            if has_oi:
                entry['open_interest'] = _val(oi_col, 0)

            result_data.append(entry)

        if old_freq:
            try:
                product.set_current_freq(old_freq)
            except Exception:
                pass

        return jsonify({
            'success': True,
            'product': product_name,
            'desc': getattr(product, 'desc', product_name),
            'adjusted': adjusted,
            'freq': freq.name if hasattr(freq, 'name') else str(freq),
            'count': len(result_data),
            'has_oi': has_oi,
            'data': result_data,
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()}), 500
