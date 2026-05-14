"""
Shared submission routes:
  GET  /get_products
  POST /submit_selected_products
  POST /reorder_submissions
  POST /delete_submission
  POST /clear_all_submissions
  POST /delete_path_of_submission
"""
from flask import request, jsonify
import time
from typing import Any, cast
from server.services.product_tree import (
    find_node_by_path, get_minimal_paths,
)
import server.services.runtime_state as runtime_state
from server.services.runtime_state import factor_testers_lock
from . import shared_bp
from .submission_helpers import (
    resolve_products_from_paths,
    submissions_payload,
)
from server.services.api_response import api_fail, api_ok, route_guard
from tools.products.Futures import FuturesContract


@shared_bp.route('/api/list_submissions')
@route_guard
def list_submissions():
    """返回当前全部有效的 FactorTester 列表（前端同步用）。"""
    return api_ok({'submissions': submissions_payload()})


@shared_bp.route('/get_products')
def get_products():
    original_path = request.args.get('path')
    if not original_path:
        return jsonify([])
    # 叶节点 checkbox 默认 True，可通过 ?checkbox=false 关闭
    leaf_checkbox = request.args.get('checkbox', 'true').lower() != 'false'
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
        }
        if is_contract:
            node_data['product_type'] = 'contract'
            node_data['contract_uid'] = prod_name
            # 合约自身通常无 desc，继承父品种的 desc
            if not prod_desc:
                from tools.products.product_utils import get_contract_desc
                prod_desc = get_contract_desc(prod_name)
                node_data['desc'] = prod_desc
        child_nodes.append(node_data)
    return jsonify(child_nodes)


@shared_bp.route('/submit_selected_products', methods=['POST'])
@route_guard
def submit_selected_products():
    data = request.get_json()
    selected_paths = data.get('selected_paths', [])
    id_time = str(data.get('id_time')) if data.get('id_time') is not None else None
    page_uuid = data.get('page_uuid', '').strip() or None
    assert selected_paths, "未选择任何产品路径"
    selected_paths, selected_products = resolve_products_from_paths(selected_paths)

    from tools.factors.FactorTester import FactorTester
    # 按 page_uuid 查找运行时时间：无记录则拒绝创建
    time_entry = runtime_state.get_current_time(page_uuid)
    if time_entry is None:
        return api_fail('请先在时间范围设置模块中设置起止时间')
    _start, _end, _start_calc = time_entry
    user = runtime_state.current_user_obj()
    factor_tester = FactorTester(products=selected_products, alias=id_time, time_range=(_start, _end), user=user)
    factor_tester.selected_paths = selected_paths  # 保存原始路径用于前端显示
    if page_uuid:
        cast(Any, factor_tester)._page_uuid = page_uuid  # 绑定页面标识，set_time_range 时可匹配更新
    if user is not None:
        user.add_tester(factor_tester)
    with factor_testers_lock:
        runtime_state.factor_testers.append(factor_tester)
    return api_ok({
        'count':               len(selected_products),
        'count_paths':         len(selected_paths),
        'selected_products':   [str(p) for p in selected_products],
        'selected_paths':      selected_paths,
        'factor_tester_name':   factor_tester.name,
        'factor_tester_serial': f"#{id_time}",
        'count_desc':          f"{len(selected_products)} 个产品",
        'submissions':         submissions_payload(),
    })


@shared_bp.route('/reorder_submissions', methods=['POST'])
@route_guard
def reorder_submissions():
    data = request.get_json()
    new_order = data.get('new_order', [])
    with factor_testers_lock:
        n = len(runtime_state.factor_testers)
        alias_to_tester = {t.alias: t for t in runtime_state.factor_testers}
        runtime_state.factor_testers[:] = [alias_to_tester[a] for a in new_order if a in alias_to_tester]
        assert len(runtime_state.factor_testers) == n, "Reordered list length mismatch"
    return api_ok()


@shared_bp.route('/delete_submission', methods=['POST'])
@route_guard
def delete_submission():
    data = request.get_json()
    id_time = str(data.get('id_time')) if data.get('id_time') is not None else None
    assert id_time is not None, "Missing id_time"
    with factor_testers_lock:
        n = len(runtime_state.factor_testers)
        tester = next(
            (
                t for t in runtime_state.factor_testers
                if runtime_state.alias_matches_submission_id(getattr(t, 'alias', ''), id_time, allow_suffix=True)
            ),
            None,
        )
        assert tester is not None, "Submission not found"
        tester.delete()
        runtime_state.factor_testers[:] = [
            t for t in runtime_state.factor_testers
            if not runtime_state.alias_matches_submission_id(getattr(t, 'alias', ''), id_time, allow_suffix=True)
        ]
        assert len(runtime_state.factor_testers) == n - 1, "No submission deleted"
    return api_ok({'submissions': submissions_payload()})


@shared_bp.route('/clear_all_submissions', methods=['POST'])
@route_guard
def clear_all_submissions():
    """清除当前页面（page_uuid）关联的 tester。

    接收 page_uuid，只清除 _page_uuid 匹配的 tester；
    同时清除无 _page_uuid 的旧 tester（向后兼容）。
    """
    data = request.get_json()
    page_uuid = data.get('page_uuid', '').strip() or None if data else None
    with factor_testers_lock:
        for tester in runtime_state.factor_testers:
            tester_puuid = getattr(tester, '_page_uuid', None)
            if tester_puuid is None or tester_puuid == page_uuid:
                try:
                    tester.delete()
                except Exception:
                    pass
        runtime_state.factor_testers[:] = [
            t for t in runtime_state.factor_testers
            if getattr(t, '_page_uuid', None) is not None and getattr(t, '_page_uuid', None) != page_uuid
        ]
    return api_ok({'submissions': submissions_payload()})


@shared_bp.route('/delete_path_of_submission', methods=['POST'])
@route_guard
def delete_path_of_submission():
    data = request.get_json()
    id_time   = str(data.get('id_time')) if data.get('id_time') is not None else None
    assert id_time is not None, "Missing id_time"
    new_paths = data.get('new_paths')
    tester = runtime_state.find_factor_tester(id_time, allow_suffix=True)
    assert tester is not None, "Submission not found"
    selected_paths, selected_products = resolve_products_from_paths(new_paths)
    tester.products = sorted(list(set(selected_products)))
    tester.selected_paths = selected_paths
    return api_ok({'submissions': submissions_payload()})
