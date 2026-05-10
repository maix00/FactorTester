"""
Shared submission / product-tree routes:
  GET  /api/tree-data
  GET  /get_products
  POST /submit_selected_products
  POST /reorder_submissions
  POST /delete_submission
  POST /clear_all_submissions
  POST /delete_path_of_submission
"""
from flask import request, jsonify
import time
from server.shared import (
    _factor_testers_lock,
    tree, convert_to_fancytree, find_node_by_path, get_minimal_paths,
)
import server.shared as shared
from . import shared_bp


def _tester_to_dict(t):
    """将 FactorTester 转为前端需要的字典。"""
    # alias 格式为 user_name:core_id，提取纯 id
    core_id = t.alias.split(':', 1)[-1] if ':' in t.alias else t.alias
    return {
        'id':                   core_id,
        'name':                 t.name,
        'product_count':        len(t.products) if hasattr(t, 'products') and t.products else 0,
        'selected_paths':       getattr(t, 'selected_paths', []) or [],
        'factor_tester_name':   t.name,
        'factor_tester_serial': f"#{core_id}" if core_id.isdigit() else t.alias,
    }


def _valid_testers():
    """返回当前有效（未被销毁）的 tester 列表。"""
    with _factor_testers_lock:
        return [t for t in shared.factor_testers if t.products and len(t.products) > 0]


@shared_bp.route('/api/tree-data')
def get_tree_data():
    if shared._fancytree_cache is None:
        shared._fancytree_cache = convert_to_fancytree(tree, checkbox_default=True)
    return jsonify(shared._fancytree_cache)


@shared_bp.route('/api/list_submissions')
def list_submissions():
    """返回当前全部有效的 FactorTester 列表（前端同步用）。"""
    try:
        testers = _valid_testers()
        return jsonify({
            'success':     True,
            'submissions': [_tester_to_dict(t) for t in testers],
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@shared_bp.route('/get_products')
def get_products():
    original_path = request.args.get('path')
    if not original_path:
        return jsonify([])
    # 叶节点 checkbox 默认 True，可通过 ?checkbox=false 关闭
    leaf_checkbox = request.args.get('checkbox', 'true').lower() != 'false'
    node_path = original_path[:-10] if original_path.endswith('/_products') else original_path
    parts = node_path.split('/')
    node = find_node_by_path(tree, parts)
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
        child_nodes.append({
            'title':        prod_name,
            'key':          f"{original_path}/{prod_id}",
            'checkbox':     leaf_checkbox,
            'folder':       False,
            'lazy':         False,
            'extraClasses': 'product-node',
            'desc':         prod_desc,
            'product_name': prod_name,
            'product_code': prod_code or (prod_name.split('.')[0] if '.' in prod_name else prod_name),
        })
    return jsonify(child_nodes)


@shared_bp.route('/submit_selected_products', methods=['POST'])
def submit_selected_products():
    data = request.get_json()
    selected_paths = data.get('selected_paths', [])
    id_time = str(data.get('id_time')) if data.get('id_time') is not None else None
    page_uuid = data.get('page_uuid', '').strip() or None
    try:
        assert selected_paths, "未选择任何产品路径"
        selected_paths = get_minimal_paths(selected_paths)
        selected_products = []
        for path in selected_paths:
            node = find_node_by_path(tree, path.split('/'))
            if isinstance(node, dict) and '$OBJECTS$' in node and isinstance(node['$OBJECTS$'], list):
                selected_products.extend(node['$OBJECTS$'])
            else:
                selected_products.append(node)
        selected_products = sorted(list(set(selected_products)))

        from tools.factors.FactorTester import FactorTester
        # 按 page_uuid 查找时间：优先 set_time_range 值，fallback Settings 默认值
        _start, _end, _start_calc = shared.get_current_time(page_uuid)
        user = shared._current_user_obj()
        factor_tester = FactorTester(products=selected_products, alias=id_time, time_range=(_start, _end), user=user)
        factor_tester.selected_paths = selected_paths  # 保存原始路径用于前端显示
        if page_uuid:
            factor_tester._page_uuid = page_uuid  # 绑定页面标识，set_time_range 时可匹配更新
        if user is not None:
            user.add_tester(factor_tester)
        with _factor_testers_lock:
            shared.factor_testers.append(factor_tester)
        return jsonify({
            'success':             True,
            'count':               len(selected_products),
            'count_paths':         len(selected_paths),
            'selected_products':   [str(p) for p in selected_products],
            'selected_paths':      selected_paths,
            'factor_tester_name':   factor_tester.name,
            'factor_tester_serial': f"#{id_time}",
            'count_desc':          f"{len(selected_products)} 个产品",
            'submissions':         [_tester_to_dict(t) for t in _valid_testers()],
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@shared_bp.route('/reorder_submissions', methods=['POST'])
def reorder_submissions():
    data = request.get_json()
    new_order = data.get('new_order', [])
    try:
        with _factor_testers_lock:
            n = len(shared.factor_testers)
            alias_to_tester = {t.alias: t for t in shared.factor_testers}
            shared.factor_testers = [alias_to_tester[a] for a in new_order if a in alias_to_tester]
            assert len(shared.factor_testers) == n, "Reordered list length mismatch"
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@shared_bp.route('/delete_submission', methods=['POST'])
def delete_submission():
    data = request.get_json()
    id_time = str(data.get('id_time')) if data.get('id_time') is not None else None
    assert id_time is not None, "Missing id_time"
    try:
        with _factor_testers_lock:
            n = len(shared.factor_testers)
            # alias 格式为 user_name:core_id，匹配尾部 id
            tester = next((t for t in shared.factor_testers if t.alias.endswith(':' + id_time) or t.alias == id_time), None)
            assert tester is not None, "Submission not found"
            tester.delete()
            shared.factor_testers = [t for t in shared.factor_testers if not (t.alias.endswith(':' + id_time) or t.alias == id_time)]
            assert len(shared.factor_testers) == n - 1, "No submission deleted"
        return jsonify({
            'success':     True,
            'submissions': [_tester_to_dict(t) for t in _valid_testers()],
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@shared_bp.route('/clear_all_submissions', methods=['POST'])
def clear_all_submissions():
    """清除当前页面（page_uuid）关联的 tester。

    接收 page_uuid，只清除 _page_uuid 匹配的 tester；
    同时清除无 _page_uuid 的旧 tester（向后兼容）。
    """
    data = request.get_json()
    page_uuid = data.get('page_uuid', '').strip() or None if data else None
    try:
        with _factor_testers_lock:
            for tester in shared.factor_testers:
                tester_puuid = getattr(tester, '_page_uuid', None)
                if tester_puuid is None or tester_puuid == page_uuid:
                    try:
                        tester.delete()
                    except Exception:
                        pass
            shared.factor_testers = [
                t for t in shared.factor_testers
                if getattr(t, '_page_uuid', None) is not None and getattr(t, '_page_uuid', None) != page_uuid
            ]
        return jsonify({
            'success':     True,
            'submissions': [_tester_to_dict(t) for t in _valid_testers()],
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@shared_bp.route('/delete_path_of_submission', methods=['POST'])
def delete_path_of_submission():
    data = request.get_json()
    id_time   = str(data.get('id_time')) if data.get('id_time') is not None else None
    assert id_time is not None, "Missing id_time"
    new_paths = data.get('new_paths')
    try:
        with _factor_testers_lock:
            tester = next((t for t in shared.factor_testers if t.alias.endswith(':' + id_time) or t.alias == id_time), None)
        assert tester is not None, "Submission not found"
        selected_paths = get_minimal_paths(new_paths)
        selected_products = []
        for path in selected_paths:
            node = find_node_by_path(tree, path.split('/'))
            if isinstance(node, dict) and '$OBJECTS$' in node and isinstance(node['$OBJECTS$'], list):
                selected_products.extend(node['$OBJECTS$'])
            else:
                selected_products.append(node)
        tester.products = sorted(list(set(selected_products)))
        return jsonify({
            'success':     True,
            'submissions': [_tester_to_dict(t) for t in _valid_testers()],
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@shared_bp.route('/replace_submissions', methods=['POST'])
def replace_submissions():
    """按给定列表一次性替换当前页面的 submissions。"""
    data = request.get_json() or {}
    tpl_submissions = data.get('template_submissions', [])
    page_uuid = (data.get('page_uuid') or '').strip() or None
    if not isinstance(tpl_submissions, list):
        return jsonify({'success': False, 'error': 'template_submissions 必须是列表'})
    try:
        from tools.factors.FactorTester import FactorTester
        user = shared._current_user_obj()
        replaced = []
        with _factor_testers_lock:
            for tester in shared.factor_testers:
                tester_puuid = getattr(tester, '_page_uuid', None)
                if tester_puuid is None or tester_puuid == page_uuid:
                    try:
                        tester.delete()
                    except Exception:
                        pass
            shared.factor_testers = [
                t for t in shared.factor_testers
                if getattr(t, '_page_uuid', None) is not None and getattr(t, '_page_uuid', None) != page_uuid
            ]

            for i, sub in enumerate(tpl_submissions):
                selected_paths = sub.get('paths') if isinstance(sub, dict) else []
                if not isinstance(selected_paths, list) or len(selected_paths) == 0:
                    continue
                selected_paths = get_minimal_paths(selected_paths)
                selected_products = []
                for path in selected_paths:
                    node = find_node_by_path(tree, path.split('/'))
                    if isinstance(node, dict) and '$OBJECTS$' in node and isinstance(node['$OBJECTS$'], list):
                        selected_products.extend(node['$OBJECTS$'])
                    else:
                        selected_products.append(node)
                selected_products = sorted(list(set(selected_products)))
                alias = str(int(time.time() * 1000) + i)
                _start, _end, _start_calc = shared.get_current_time(page_uuid)
                factor_tester = FactorTester(products=selected_products, alias=alias, time_range=(_start, _end), user=user)
                factor_tester.selected_paths = selected_paths
                if page_uuid:
                    factor_tester._page_uuid = page_uuid
                if user is not None:
                    user.add_tester(factor_tester)
                shared.factor_testers.append(factor_tester)
                replaced.append({
                    'id': alias,
                    'paths': selected_paths,
                    'label': sub.get('label', '') if isinstance(sub, dict) else '',
                    'factor_tester_name': factor_tester.name,
                    'factor_tester_serial': f"#{alias}",
                    'count_desc': f"{len(selected_products)} 个产品",
                })
        return jsonify({
            'success': True,
            'replaced_submissions': replaced,
            'submissions': [_tester_to_dict(t) for t in _valid_testers()],
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
