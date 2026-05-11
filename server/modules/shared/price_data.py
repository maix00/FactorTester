"""
序列查看 API
  GET  /api/list_product_names  — 获取所有可查看价格的品种名称列表
  GET  /api/product_tree        — 获取产品类别树（复用 CategoryTree，支持多产品类型）
  GET  /api/get_contracts       — 获取主力品种对应的合约列表
  POST /api/get_price_data      — 获取指定品种的价格序列（复权/非复权，支持合约级别）
"""
import os
import traceback
import pandas as pd
from flask import request, jsonify
from . import shared_bp
from server.services.product_tree import convert_to_fancytree, find_node_by_path
from tools.data.DataSource import DataSource
from tools.products.Futures import Futures
from tools.products.product_utils import get_contract_desc, get_product_contracts
from .price_data_helpers import format_price_row, to_utc_epoch
from server.modules.shared.price_services import (
    available_freq_names_for_product as _available_freq_names_for_product,
    available_sources_for_product as _available_sources_for_product,
    cached_contracts as _cached_contracts,
    cached_price_viewer_tree as _cached_price_viewer_tree,
    cached_products as _cached_products,
    contract_data_path as _contract_data_path,
    contract_has_data as _contract_has_data,
    find_contract_product as _find_contract_product,
    find_product as _find_product,
    supports_adjusted_price as _supports_adjusted_price,
    supports_term_structure as _supports_term_structure,
)


@shared_bp.route('/api/list_product_names')
def list_product_names():
    """返回所有品种的中英文名称列表。"""
    try:
        products = _cached_products()
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
                'type': 'product',
            })
        return jsonify({'success': True, 'products': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()}), 500


@shared_bp.route('/api/product_tree')
def get_product_tree():
    """返回产品类别树（Fancytree 格式），支持所有产品类型。"""
    try:
        cat_tree = _cached_price_viewer_tree()
        fancytree_data = convert_to_fancytree(cat_tree.tree, checkbox_default=False)
        return jsonify(fancytree_data)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()}), 500


@shared_bp.route('/api/contract_tree')
def get_contract_tree():
    """返回合约粒度的产品节点，供价格页左侧懒加载。"""
    try:
        path = request.args.get('path')
        if path:
            node_path = path[:-10] if path.endswith('/_products') else path
            node = find_node_by_path(_cached_price_viewer_tree().tree, node_path.split('/'))
            contracts = node.get('$OBJECTS$', []) if isinstance(node, dict) else ([node] if node else [])
        else:
            contracts = _cached_contracts()
        contracts = sorted(contracts, key=lambda x: getattr(x, 'name', str(x)))
        nodes = []
        for c in contracts:
            name = getattr(c, 'name', str(c))
            has_data = _contract_has_data(name)
            nodes.append({
                'title': name,
                'key': f"CNFuturesContract/{name}",
                'checkbox': False,
                'folder': False,
                'lazy': False,
                'extraClasses': 'product-node contract-node' + ('' if has_data else ' disabled-contract-node'),
                'desc': '合约' if has_data else '暂无价格数据',
                'product_name': name,
                'product_code': name,
                'product_type': 'contract',
                'contract_uid': name,
                'has_data': has_data,
            })
        return jsonify(nodes)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()}), 500

@shared_bp.route('/api/get_contracts')
def get_contracts():
    """
    返回指定主力品种的合约列表（按时间排序）。

    请求参数：
        product : 品种名称（如 'A.DCE'）

    返回：
        {
            success: true,
            product: 'A.DCE',
            contracts: [{ contract: 'A2505.DCE', uid: 'DCE|F|A|2505', desc: '...', start: '...', end: '...', has_data: true }, ...]
        }
    """
    product_name = request.args.get('product')
    if not product_name:
        return jsonify({'success': False, 'error': '缺少 product 参数'}), 400

    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    try:
        products = _cached_products()
        product = _find_product(products, product_name)

        if not product:
            return jsonify({'success': False, 'error': f'未找到品种: {product_name}'}), 404

        if not _supports_term_structure(product):
            return jsonify({
                'success': True,
                'product': product_name,
                'supports_term_structure': False,
                'has_term_structure': False,
                'contracts': [],
            })

        contracts = get_product_contracts(product, start_date=start_date, end_date=end_date)

        # 补充 has_data（合约价格文件是否存在）
        for c in contracts:
            c['has_data'] = _contract_has_data(c['uid'])

        return jsonify({
            'success': True,
            'product': product_name,
            'supports_term_structure': True,
            'has_term_structure': True,
            'contracts': contracts,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()}), 500


@shared_bp.route('/api/get_price_data', methods=['POST'])
def get_price_data():
    """
    获取指定品种的价格序列。

    请求参数：
        product_name : 品种名称（如 'IF.CFE'）
        contract_uid : 合约 UID（如 'DCE|F|A|2505'），设置后直接读合约原始分钟数据
        adjusted     : 是否复权 (默认 false)
        freq         : 数据频率 'DAY1' | 'MIN1' (默认 'DAY1')
        start_date   : 开始日期 'YYYY-MM-DD' (可选)
        end_date     : 结束日期 'YYYY-MM-DD' (可选)

    返回：
        {
            success: true,
            product: 'IF.CFE',
            contract_uid: '...',   // 仅在请求合约时返回
            adjusted: false,
            freq: 'DAY1',
            contracts: [...],      // 支持期限结构时返回合约区间（用于高亮）
            data: [{ time: '...', open: ..., high: ..., low: ..., close: ..., volume: ... }, ...]
        }
    """
    data = request.get_json()
    product_name = data.get('product_name')
    contract_uid = data.get('contract_uid')
    adjusted = data.get('adjusted', False)
    freq_str = data.get('freq', 'DAY1')
    data_source_alias = data.get('data_source')
    start_date = data.get('start_date')
    end_date = data.get('end_date')

    if not product_name and not contract_uid:
        return jsonify({'success': False, 'error': '缺少 product_name 或 contract_uid'}), 400

    try:
        # ========== 合约模式：直接读原始合约数据 ==========
        if contract_uid:
            contract_product = _find_contract_product(contract_uid)
            available_freqs = _available_freq_names_for_product(contract_product) if contract_product else []
            available_sources = _available_sources_for_product(contract_product) if contract_product else []

            contract_file = _contract_data_path(contract_uid)
            if not os.path.exists(contract_file):
                return jsonify({'success': False, 'error': f'合约数据不存在: {contract_uid}'}), 404

            price_df = pd.read_parquet(contract_file)
            if price_df.empty:
                return jsonify({'success': False, 'error': '合约数据为空'}), 404

            from tools.data.DataFreq import DataFreq
            try:
                freq = DataFreq(freq_str)
            except Exception:
                freq = DataFreq('MIN1')
            if available_freqs and freq.name not in available_freqs:
                freq = DataFreq(available_freqs[0])

            freq_is_daily = freq.is_day_multiple()

            if freq_is_daily:
                price_df['trading_day'] = pd.to_datetime(price_df['trading_day'])
                price_df = price_df.groupby('trading_day').agg(
                    open=('open_price', 'first'),
                    high=('highest_price', 'max'),
                    low=('lowest_price', 'min'),
                    close=('close_price', 'last'),
                    volume=('volume', 'sum'),
                    open_interest=('open_interest', 'last'),
                ).reset_index().rename(columns={'trading_day': 'time_idx'})
                o_col, h_col, l_col, c_col, v_col = 'open', 'high', 'low', 'close', 'volume'
                oi_col = 'open_interest'
                time_col = 'time_idx'
            else:
                price_df['trade_time'] = pd.to_datetime(price_df['trade_time'])
                price_df = price_df.sort_values('trade_time')
                o_col, h_col, l_col, c_col, v_col = (
                    'open_price', 'highest_price', 'lowest_price', 'close_price', 'volume'
                )
                oi_col = 'open_interest'
                time_col = 'trade_time'

            # 合约模式也要严格应用时间范围截断
            if start_date:
                start_ts = pd.Timestamp(start_date)
                price_df = price_df[price_df[time_col] >= start_ts]
            if end_date:
                end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)
                price_df = price_df[price_df[time_col] <= end_ts]

            if price_df.empty:
                return jsonify({'success': False, 'error': '指定范围内无合约价格数据'}), 404

            has_oi = oi_col in price_df.columns

            # 获取合约所属产品的时区（用于 naive datetime 的 localize）
            contract_tz = getattr(contract_product, 'timezone', None) or 'Asia/Shanghai'

            result_data = [
                format_price_row(
                    row=row,
                    time_col=time_col,
                    o_col=o_col,
                    h_col=h_col,
                    l_col=l_col,
                    c_col=c_col,
                    v_col=v_col,
                    oi_col=oi_col if has_oi else None,
                    freq_is_daily=freq_is_daily,
                    timezone=contract_tz,
                )
                for _, row in price_df.iterrows()
            ]

            return jsonify({
                'success': True,
                'product': contract_uid,
                'contract_uid': contract_uid,
                'contract_name': contract_uid.split('|')[-2] + contract_uid.split('|')[-1] if '|' in contract_uid else contract_uid,
                'is_term_contract': True,
                'adjusted': False,
                'supports_adjusted': False,
                'supports_term_structure': False,
                'freq': freq.name if hasattr(freq, 'name') else str(freq),
                'data_source': (available_sources[0]['alias'] if available_sources else ''),
                'available_sources': available_sources,
                'available_freqs': available_freqs,
                'count': len(result_data),
                'has_oi': has_oi,
                'data': result_data,
            })

        # ========== 产品价格模式 ==========
        products = _cached_products()
        product = _find_product(products, product_name)

        if not product:
            return jsonify({'success': False, 'error': f'未找到品种: {product_name}'}), 404
        supports_adjusted = _supports_adjusted_price(product)
        adjusted = bool(adjusted and supports_adjusted)

        from tools.data.DataFreq import DataFreq
        candidate_source = None
        if data_source_alias:
            try:
                candidate_source = DataSource[data_source_alias]
                freq = candidate_source.freq
            except Exception:
                return jsonify({'success': False, 'error': f'数据源不存在: {data_source_alias}'}), 400
        else:
            try:
                freq = DataFreq(freq_str)
            except Exception:
                freq = DataFreq('DAY1')

        old_freq = getattr(product, 'current_freq', None)
        old_source = None
        try:
            product.set_current_freq(freq)
        except ValueError:
            # 回退到默认
            available = product.list_available_freqs()
            if not available:
                return jsonify({'success': False, 'error': '无可用数据频率'}), 400
            freq = available[0]
            product.set_current_freq(freq)
        data_meta = getattr(product, freq.name)
        if hasattr(data_meta, 'current_source'):
            old_source = data_meta.current_source
        selected_source = None
        if candidate_source is not None:
            try:
                selected_source = data_meta.set_current_source(candidate_source)
            except Exception:
                return jsonify({'success': False, 'error': f'数据源不可用于该品种和频率: {data_source_alias}'}), 400

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

        # 时区统一：日内数据统一到 product 时区，日频数据保持 naive
        # format_price_row 会将所有时间统一转为 UTC epoch，前端按浏览器本地时区渲染
        idx_tz = getattr(price_df.index, 'tz', None)
        product_tz = getattr(product, 'timezone', None) or 'Asia/Shanghai'
        if idx_tz is not None and str(idx_tz) != product_tz:
            price_df.index = price_df.index.tz_convert(product_tz)

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

        price_df_for_emit = price_df.copy()
        price_df_for_emit['__time__'] = [idx for idx in price_df_for_emit.index]
        result_data = [
            format_price_row(
                row=row,
                time_col='__time__',
                o_col=o_col,
                h_col=h_col,
                l_col=l_col,
                c_col=c_col,
                v_col=v_col,
                oi_col=oi_col if has_oi else None,
                freq_is_daily=freq_is_daily,
                timezone=product_tz,
            )
            for _, row in price_df_for_emit.iterrows()
        ]

        active_source_used = selected_source
        if active_source_used is None:
            try:
                active_source_used = data_meta.get_current_source()
            except Exception:
                active_source_used = None

        if old_freq:
            try:
                product.set_current_freq(old_freq)
            except Exception:
                pass
        if old_source:
            try:
                data_meta.set_current_source(old_source)
            except Exception:
                pass

        supports_term_structure = _supports_term_structure(product)

        # 支持期限结构的产品：附带合约区间列表（用于高亮）
        contracts = []
        if supports_term_structure:
            try:
                from tools.products.product_utils import get_product_contracts
                raw = get_product_contracts(product)
                for c in raw:
                    contracts.append({
                        'contract': c['contract'],
                        'uid': c['uid'],
                        'has_data': _contract_has_data(c['uid']),
                        'start_ts': c.get('start_ts'),
                        'end_ts': c.get('end_ts'),
                    })
            except Exception:
                pass

        available_sources = _available_sources_for_product(product)
        available_freqs = _available_freq_names_for_product(product)

        return jsonify({
            'success': True,
            'product': product_name,
            'desc': getattr(product, 'desc', product_name),
            'product_type': 'futures' if isinstance(product, Futures) else 'product',
            'is_term_contract': False,
            'adjusted': adjusted,
            'supports_adjusted': supports_adjusted,
            'supports_term_structure': supports_term_structure,
            'freq': freq.name if hasattr(freq, 'name') else str(freq),
            'data_source': getattr(active_source_used, 'alias', ''),
            'available_sources': available_sources,
            'available_freqs': available_freqs,
            'count': len(result_data),
            'has_oi': has_oi,
            'contracts': contracts,
            'data': result_data,
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()}), 500
