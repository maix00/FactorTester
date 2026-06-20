"""
Shared submission routes:
  GET  /get_products
  POST /submit_selected_products
  POST /reorder_submissions
  POST /delete_submission
  POST /clear_all_submissions
  POST /delete_path_of_submission
  POST /update_submission_paths
  POST /rename_submission
"""
from flask import request, jsonify
import time
from typing import Any, cast
from server.services.product_tree import (
    find_node_by_path, get_minimal_paths,
)
import server.services.page_runtime as runtime_state
from server.services.page_runtime import factor_testers_lock
from server.services.session_runtime import current_user_obj
from . import shared_bp
from .submission_helpers import resolve_products_from_paths, submissions_payload
from .submission_ids import make_submission_id
from server.services.api_response import api_fail, api_ok, route_guard
from tools.products.Futures import FuturesContract
from server.modules.shared.price_services import product_public_fields


def _request_page_uuid(data: dict | None = None) -> str | None:
    raw = (data or {}).get('page_uuid', '') if data is not None else request.args.get('page_uuid', '')
    return str(raw).strip() or None


def _require_page_uuid(data: dict | None = None):
    page_uuid = _request_page_uuid(data)
    if not page_uuid:
        return None, api_fail('缺少 page_uuid，请先打开页面并生成页面上下文')
    return page_uuid, None


def _matches_page(tester: Any, page_uuid: str | None) -> bool:
    return page_uuid is None or getattr(tester, '_page_uuid', None) == page_uuid


def _find_submission(id_time: str, page_uuid: str | None):
    return next(
        (
            tester for tester in runtime_state.iter_factor_testers(page_uuid)
            if runtime_state.alias_matches_submission_id(
                getattr(tester, 'alias', ''), id_time, allow_suffix=True
            )
        ),
        None,
    )


def _trailing_year_volume_stats(product):
    """Return daily-volume liquidity summaries relative to the latest data date."""
    import pandas as pd
    from tools.data.types import DataColumn

    empty_result = {
        'latest_volume': None,
        'average_daily_volume_1y': None,
        'zero_volume_days_1y': None,
        'volume_stats_as_of': None,
    }
    try:
        data = product.get_slices(
            target_cols=DataColumn.VOLUME,
            time_col='DAY1',
            data_freq='DAY1',
            copy=False,
        )
    except Exception:
        return empty_result
    volume_column = DataColumn.VOLUME.name
    if data.empty or volume_column not in data.columns:
        return empty_result

    if isinstance(data.index, pd.MultiIndex):
        date_index = pd.to_datetime(data.index.get_level_values('DAY1' if 'DAY1' in data.index.names else 0))
    else:
        date_index = pd.to_datetime(data.index)
    daily = pd.Series(pd.to_numeric(data[volume_column], errors='coerce').values, index=date_index)
    daily = daily.groupby(daily.index.normalize()).sum(min_count=1).dropna().sort_index()
    if daily.empty:
        return empty_result

    latest_date = daily.index[-1]
    trailing = daily[daily.index >= latest_date - pd.DateOffset(years=1)]
    return {
        'latest_volume': float(daily.iloc[-1]),
        'average_daily_volume_1y': float(trailing.mean()),
        'zero_volume_days_1y': int((trailing <= 0).sum()),
        'volume_stats_as_of': latest_date.strftime('%Y-%m-%d'),
    }


@shared_bp.route('/api/list_submissions')
@route_guard
def list_submissions():
    """返回当前全部有效的 FactorTester 列表（前端同步用）。"""
    page_uuid, err = _require_page_uuid()
    if err is not None:
        return err
    return api_ok({'submissions': submissions_payload(page_uuid)})


@shared_bp.route('/get_products')
def get_products():
    original_path = request.args.get('path')
    if not original_path:
        return jsonify([])
    # 叶节点 checkbox 默认 True，可通过 ?checkbox=false 关闭
    leaf_checkbox = request.args.get('checkbox', 'true').lower() != 'false'
    include_volume_stats = request.args.get('include_volume_stats', 'false').lower() == 'true'
    include_series_variants = request.args.get('series_variants', 'false').lower() == 'true'
    from server.modules.shared.price_services import cached_product_tree
    search_tree = cached_product_tree().tree
    node_path = original_path[:-10] if original_path.endswith('/_products') else original_path
    parts = node_path.split('/')
    node = find_node_by_path(search_tree, parts)
    if node is None:
        return jsonify([])
    objects = node.get('$OBJECTS$', []) if isinstance(node, dict) else [node]
    objects = sorted(objects, key=lambda x: getattr(x, 'name', str(x)))
    child_nodes = []
    for prod in objects:
        prod_id   = getattr(prod, 'id',   str(prod))
        prod_name = getattr(prod, 'name', str(prod))
        prod_desc = getattr(prod, 'desc', '')
        prod_code = getattr(prod, 'code', None)
        is_contract = isinstance(prod, FuturesContract)
        node_data = {
            'title':        prod_name,
            'key':          f"{original_path}/{prod_id}",
            'checkbox':     leaf_checkbox,
            'folder':       False,
            'lazy':         False,
            'extraClasses': 'product-node',
            'desc':         prod_desc,
            'product_name': prod_name,
            'product_code': prod_code or (prod_name.split('.')[0] if '.' in prod_name else prod_name),
            'fields':       product_public_fields(prod),
        }
        if include_series_variants and not is_contract:
            variants = list(getattr(prod, "get_series_variants", lambda: [])())
            node_data.update({
                'folder': True,
                'children': [
                    {
                        'title': ref.label,
                        'key': f"{original_path}/{prod_id}/_series/{ref.variant}",
                        'checkbox': False,
                        'folder': False,
                        'lazy': False,
                        'extraClasses': 'product-node series-variant-node',
                        'desc': ref.label,
                        'product_name': prod_name,
                        'product_code': prod_code or (prod_name.split('.')[0] if '.' in prod_name else prod_name),
                        'series_variant': ref.variant,
                        'adjusted': ref.adjusted,
                    }
                    for ref in variants
                ],
            })
        if is_contract:
            node_data['product_type'] = 'contract'
            node_data['contract_uid'] = prod_name
            # 合约自身通常无 desc，继承父品种的 desc
            if not prod_desc:
                from tools.products.product_utils import get_contract_desc
                prod_desc = get_contract_desc(prod_name)
                node_data['desc'] = prod_desc
        if include_volume_stats:
            node_data.update(_trailing_year_volume_stats(prod))
        child_nodes.append(node_data)
    return jsonify(child_nodes)


@shared_bp.route('/submit_selected_products', methods=['POST'])
@route_guard
def submit_selected_products():
    data = request.get_json()
    page_uuid, err = _require_page_uuid(data)
    if err is not None:
        return err
    selected_paths = data.get('selected_paths', [])
    id_time = make_submission_id(data.get('id_time'))
    group_name = data.get('group_name', '').strip() or None
    assert selected_paths, "未选择任何产品路径"
    selected_paths, selected_products = resolve_products_from_paths(selected_paths)

    from tools.factors.FactorTester import FactorTester
    # 按 page_uuid 查找运行时时间：无记录则拒绝创建
    time_entry = runtime_state.get_current_time(page_uuid)
    if time_entry is None:
        return api_fail('请先在时间范围设置模块中设置起止时间')
    _start, _end, _start_calc = time_entry
    user = current_user_obj()
    factor_tester = FactorTester(products=selected_products, alias=id_time, start_dt=_start, end_dt=_end, user=user)
    factor_tester.selected_paths = selected_paths  # 保存原始路径用于前端显示
    if group_name:
        factor_tester.product_group = group_name
    if page_uuid:
        cast(Any, factor_tester)._page_uuid = page_uuid  # 绑定页面标识，set_time_range 时可匹配更新
    runtime_state.register_factor_tester(factor_tester, page_uuid=page_uuid)
    return api_ok({
        'count':               len(selected_products),
        'count_paths':         len(selected_paths),
        'selected_products':   [str(p) for p in selected_products],
        'selected_paths':      selected_paths,
        'factor_tester_name':   factor_tester.name,
        'factor_tester_serial': f"#{id_time}",
        'count_desc':          f"{len(selected_products)} 个产品",
        'submissions':         submissions_payload(page_uuid),
    })


@shared_bp.route('/reorder_submissions', methods=['POST'])
@route_guard
def reorder_submissions():
    data = request.get_json()
    page_uuid, err = _require_page_uuid(data)
    if err is not None:
        return err
    new_order = data.get('new_order', [])
    scoped_testers = runtime_state.iter_factor_testers(page_uuid)
    alias_to_tester = {}
    for t in scoped_testers:
        core_id = t.alias.split(':', 1)[-1] if ':' in t.alias else t.alias
        alias_to_tester[core_id] = t
    ordered = [alias_to_tester[a] for a in new_order if a in alias_to_tester]
    if len(ordered) != len(scoped_testers) or {id(t) for t in ordered} != {id(t) for t in scoped_testers}:
        return api_fail(f'排序失败: 期望{len(scoped_testers)}条，实际匹配{len(ordered)}条')
    runtime_state.replace_page_factor_testers(page_uuid, ordered)
    return api_ok({'submissions': submissions_payload(page_uuid)})


@shared_bp.route('/update_submission_paths', methods=['POST'])
@route_guard
def update_submission_paths():
    data = request.get_json()
    page_uuid, err = _require_page_uuid(data)
    if err is not None:
        return err
    id_time = str(data.get('id_time')) if data.get('id_time') is not None else None
    assert id_time is not None, "Missing id_time"
    selected_paths = data.get('selected_paths', [])
    new_name = (data.get('new_name') or '').strip()
    selected_paths, selected_products = resolve_products_from_paths(selected_paths)
    assert selected_paths, "未选择任何产品路径"
    with factor_testers_lock:
        tester = _find_submission(id_time, page_uuid)
        assert tester is not None, "Submission not found"
        tester.products = sorted(list(set(selected_products)))
        tester.selected_paths = selected_paths
        if new_name:
            tester.label = new_name
    return api_ok({'submissions': submissions_payload(page_uuid)})


@shared_bp.route('/rename_submission', methods=['POST'])
@route_guard
def rename_submission():
    data = request.get_json()
    page_uuid, err = _require_page_uuid(data)
    if err is not None:
        return err
    id_time = str(data.get('id_time')) if data.get('id_time') is not None else None
    assert id_time is not None, "Missing id_time"
    new_name = (data.get('new_name') or '').strip()
    assert new_name, "新名称不能为空"
    with factor_testers_lock:
        tester = _find_submission(id_time, page_uuid)
        assert tester is not None, "Submission not found"
        tester.label = new_name
    return api_ok({'submissions': submissions_payload(page_uuid)})


@shared_bp.route('/delete_submission', methods=['POST'])
@route_guard
def delete_submission():
    data = request.get_json()
    page_uuid, err = _require_page_uuid(data)
    if err is not None:
        return err
    id_time = str(data.get('id_time')) if data.get('id_time') is not None else None
    assert id_time is not None, "Missing id_time"
    tester = _find_submission(id_time, page_uuid)
    assert tester is not None, "Submission not found"
    runtime_state.remove_factor_tester(tester, delete=True)
    return api_ok({'submissions': submissions_payload(page_uuid)})


@shared_bp.route('/clear_all_submissions', methods=['POST'])
@route_guard
def clear_all_submissions():
    """清除当前页面（page_uuid）关联的 tester。

    page_uuid 由页面在打开时提前生成并传回后端；这里仅清理该页。
    """
    data = request.get_json()
    page_uuid, err = _require_page_uuid(data)
    if err is not None:
        return err
    runtime_state.clear_page_factor_testers(page_uuid, delete=True)
    return api_ok({'submissions': submissions_payload(page_uuid)})


@shared_bp.route('/delete_path_of_submission', methods=['POST'])
@route_guard
def delete_path_of_submission():
    data = request.get_json()
    page_uuid, err = _require_page_uuid(data)
    if err is not None:
        return err
    id_time   = str(data.get('id_time')) if data.get('id_time') is not None else None
    assert id_time is not None, "Missing id_time"
    new_paths = data.get('new_paths')
    selected_paths, selected_products = resolve_products_from_paths(new_paths)
    with factor_testers_lock:
        tester = _find_submission(id_time, page_uuid)
        assert tester is not None, "Submission not found"
        tester.products = sorted(list(set(selected_products)))
        tester.selected_paths = selected_paths
    return api_ok({'submissions': submissions_payload(page_uuid)})
