"""
价格序列查看 API
  GET  /api/list_product_names  — 获取所有可查看价格的品种名称列表
  GET  /api/product_tree        — 获取产品类别树（复用 CategoryTree，支持多产品类型）
  GET  /api/get_contracts       — 获取主力品种对应的合约列表
  POST /api/get_price_data      — 获取指定品种的价格序列（复权/非复权，支持合约级别）
"""
import os
import traceback
from functools import lru_cache
from typing import Any
import numpy as np
import pandas as pd
from flask import request, jsonify
from . import shared_bp
from Settings import get_all_products, get_cat_tree
from server.shared import convert_to_fancytree, find_node_by_path
from sources.LocalCNFutures import MINK_PRODUCT_DIR
from sources.LocalCNFutures.CNFutures import (
    CNFuturesContract,
    CNFuturesDayNightTimeCategory,
    CNFuturesSectorCategory,
    exchange_map,
    get_all_futures_contract,
)
from tools.data.DataSource import DataSource
from tools.products.Futures import (
    Futures,
    FuturesContract,
    make_contract_category_from_futures_category,
    map_contracts_to_futures,
)
from tools.products.AdjustableTermStructure import AdjustableProductMixin
from tools.products.Product import Product
from tools.products.categories.Category import CategoryTree, combine_trees


@lru_cache(maxsize=1)
def _cached_products():
    return tuple(get_all_products())


@lru_cache(maxsize=1)
def _cached_contracts():
    return tuple(get_all_futures_contract())


@lru_cache(maxsize=1)
def _cached_price_viewer_tree() -> CategoryTree:
    return _build_price_viewer_tree()


def _contract_data_path(contract_uid: str) -> str:
    return os.path.join(MINK_PRODUCT_DIR, f"{contract_uid}.parquet")


def _contract_has_data(contract_uid: str) -> bool:
    return os.path.isfile(_contract_data_path(contract_uid))


def _scalar(value: Any) -> Any:
    return value.item() if hasattr(value, 'item') else value


def _timestamp_or_none(value: Any) -> pd.Timestamp | None:
    value = _scalar(value)
    if pd.isna(value):
        return None
    return pd.Timestamp(value)


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


def _build_price_viewer_tree() -> CategoryTree:
    """价格页产品树：原品种分类 + 合约类型继承链。

    CNFuturesContract 不是根级分类，而是 FuturesContract 的具体子类；
    同时它应继承对应 CNFutures 主力品种的行业/日夜盘分类，方便按同一语义浏览合约。
    """
    product_tree = get_cat_tree()
    contracts = list(_cached_contracts())
    contract_tree = _get_contract_category_tree(contracts)
    return combine_trees(product_tree, contract_tree)


def _get_contract_category_tree(contracts) -> CategoryTree:
    """Build a CNFuturesContract tree that mirrors CNFutures category labels."""
    contract_to_future = _map_contracts_to_futures(contracts)

    sector_category = make_contract_category_from_futures_category(
        CNFuturesSectorCategory,
        CNFuturesContract,
        contracts,
        contract_to_future,
    )
    daynight_category = make_contract_category_from_futures_category(
        CNFuturesDayNightTimeCategory,
        CNFuturesContract,
        contracts,
        contract_to_future,
    )

    return (sector_category * daynight_category).get_tree_with_parents(
        all_objects=contracts,
        ancester=Product,
    )


def _map_contracts_to_futures(contracts):
    return map_contracts_to_futures(
        contracts,
        _cached_products(),
        contract_key=_contract_code_exchange,
        futures_key=_future_code_exchange,
    )


def _future_code_exchange(future):
    code = str(getattr(future, 'code', '')).upper()
    alias = str(getattr(future, 'alias', getattr(future, 'name', '')))
    exchange = alias.split('.')[1].split('@')[0].upper() if '.' in alias else ''
    return (code, exchange) if code and exchange else None


def _contract_code_exchange(contract):
    name = str(getattr(contract, 'name', getattr(contract, 'alias', contract)))
    if '|' in name:
        parts = name.split('|')
        if len(parts) >= 3:
            exchange = exchange_map.get(parts[0], parts[0]).upper()
            code = parts[2].upper()
            return code, exchange

    import re
    match = re.match(r'^([A-Za-z]+)\d+\.?([A-Za-z]+)?', name)
    if match:
        code = match.group(1).upper()
        exchange = exchange_map.get(match.group(2) or '', match.group(2) or '').upper()
        return (code, exchange) if exchange else None
    return None


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


def _available_sources_for_product(product, freq=None):
    """Serialize available data sources for one product/frequency."""
    try:
        sources = []
        freqs = [freq] if freq is not None else product.list_available_freqs()
        for f in freqs:
            meta = getattr(product, f.name)
            for source in meta.list_available_sources():
                sources.append({
                    'alias': source.alias,
                    'freq': source.freq.name if hasattr(source.freq, 'name') else str(source.freq),
                })
        unique = {}
        for source in sources:
            unique[source['alias']] = source
        return list(unique.values())
    except Exception:
        return []


def _available_freq_names_for_product(product):
    """Return frequency names that are actually provided by available data sources."""
    freqs = []
    try:
        for source in _available_sources_for_product(product):
            freq = source.get('freq')
            if freq and freq not in freqs:
                freqs.append(freq)
    except Exception:
        pass
    return freqs


def _find_contract_product(contract_uid):
    contracts = _cached_contracts()
    return next((c for c in contracts if c is not None and (
        getattr(c, 'name', None) == contract_uid or
        getattr(c, 'alias', None) == contract_uid
    )), None)


def _supports_adjusted_price(product) -> bool:
    """Whether this product supports adjusted OHLC prices."""
    supports = getattr(product, 'supports_adjusted_price', None)
    if callable(supports):
        return bool(supports())
    return isinstance(product, AdjustableProductMixin)


def _supports_term_structure(product) -> bool:
    """Whether this product supports term-structure/contract-chain views."""
    supports = getattr(product, 'supports_term_structure', None)
    if callable(supports):
        return bool(supports())
    return isinstance(product, AdjustableProductMixin)


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
            contracts: [{ contract: 'A2505.DCE', uid: 'DCE|F|A|2505', start: '...', end: '...' }, ...]
        }
    """
    product_name = request.args.get('product')
    if not product_name:
        return jsonify({'success': False, 'error': '缺少 product 参数'}), 400

    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    try:
        # 先找到 product 对象，确定数据源
        products = _cached_products()
        product = next((p for p in products if p is not None and (
            getattr(p, 'name', None) == product_name or
            getattr(p, 'alias', None) == product_name
        )), None)

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

        # 通过实例加载 roller_info（带全局缓存、闲置自动释放）
        ensure_roller_info = getattr(product, '_ensure_roller_info', None)
        if not callable(ensure_roller_info):
            return jsonify({
                'success': True,
                'product': product_name,
                'supports_term_structure': True,
                'has_term_structure': True,
                'contracts': [],
            })
        ensure_roller_info()
        subset = product.roller_info
        if subset is None or subset.empty:
            return jsonify({
                'success': True,
                'product': product_name,
                'supports_term_structure': True,
                'has_term_structure': True,
                'contracts': [],
            })

        req_start = pd.Timestamp(start_date).normalize() if start_date else None
        req_end = pd.Timestamp(end_date).normalize() if end_date else None

        contracts = []
        for _, row in subset.iterrows():
            start = _timestamp_or_none(row['STARTDATE'])
            end = _timestamp_or_none(row['ENDDATE'])

            # 只返回与请求时间范围有重叠的合约
            if req_start is not None and end is not None and end.normalize() < req_start:
                continue
            if req_end is not None and start is not None and start.normalize() > req_end:
                continue

            uid = str(_scalar(row['CONTRACT_UID']))
            contracts.append({
                'contract': str(_scalar(row['CONTRACT'])),
                'uid': uid,
                'has_data': _contract_has_data(uid),
                'start': start.strftime('%Y-%m-%d') if start is not None else None,
                'end': end.strftime('%Y-%m-%d') if end is not None else None,
                'start_ts': int(start.timestamp() * 1000) if start is not None else None,
                'end_ts': int(end.timestamp() * 1000) if end is not None else None,
            })

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
            contracts: [...],      // 主力连续时返回合约区间（用于高亮）
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

            result_data = []
            for _, row in price_df.iterrows():
                ts = pd.Timestamp(_scalar(row[time_col]))
                time_str = ts.strftime('%Y-%m-%d' if freq_is_daily else '%Y-%m-%d %H:%M:%S')
                timestamp_ms = int(ts.timestamp() * 1000)

                entry = {'time': time_str, 'timestamp': timestamp_ms}

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

            return jsonify({
                'success': True,
                'product': contract_uid,
                'contract_uid': contract_uid,
                'contract_name': contract_uid.split('|')[-2] + contract_uid.split('|')[-1] if '|' in contract_uid else contract_uid,
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

        # ========== 主力连续模式 ==========
        products = _cached_products()
        product = next((p for p in products if p is not None and (
            getattr(p, 'name', None) == product_name or
            getattr(p, 'alias', None) == product_name
        )), None)

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
            ts_val: pd.Timestamp = pd.Timestamp(str(idx))
            time_str = ts_val.strftime('%Y-%m-%d' if freq_is_daily else '%Y-%m-%d %H:%M:%S')
            timestamp_ms = int(ts_val.timestamp() * 1000)

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

        # 主力连续模式：附带合约区间列表（用于高亮）
        contracts = []
        if supports_term_structure:
            try:
                ensure_roller_info = getattr(product, '_ensure_roller_info', None)
                if callable(ensure_roller_info):
                    ensure_roller_info()
                    ri = product.roller_info
                    if ri is not None:
                        for _, r in ri.iterrows():
                            s, e = _timestamp_or_none(r['STARTDATE']), _timestamp_or_none(r['ENDDATE'])
                            uid = str(_scalar(r['CONTRACT_UID']))
                            contracts.append({
                                'contract': str(_scalar(r['CONTRACT'])),
                                'uid': uid,
                                'has_data': _contract_has_data(uid),
                                'start_ts': int(s.timestamp() * 1000) if s is not None else None,
                                'end_ts': int(e.timestamp() * 1000) if e is not None else None,
                            })
            except Exception:
                pass

        available_sources = _available_sources_for_product(product)
        available_freqs = _available_freq_names_for_product(product)

        return jsonify({
            'success': True,
            'product': product_name,
            'desc': getattr(product, 'desc', product_name),
            'is_futures': isinstance(product, Futures),
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
