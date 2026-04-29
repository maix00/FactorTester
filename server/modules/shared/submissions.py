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
from server.shared import (
    _factor_testers_lock,
    tree, convert_to_fancytree, find_node_by_path, get_minimal_paths,
)
import server.shared as shared
from . import shared_bp


@shared_bp.route('/api/tree-data')
def get_tree_data():
    if shared._fancytree_cache is None:
        shared._fancytree_cache = convert_to_fancytree(tree, checkbox_default=True)
    return jsonify(shared._fancytree_cache)


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
        _start = shared.start_point
        _end   = shared.end_point
        if _start is None or _end is None:
            from Settings import default_test_start_date, default_test_end_date
            _start, _end = default_test_start_date, default_test_end_date
        user = shared._current_user_obj()
        factor_tester = FactorTester(products=selected_products, alias=id_time, time_range=(_start, _end), user=user)
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
            'factor_tester_serial': factor_tester.alias,
            'count_desc':          f"{len(selected_products)} 个产品",
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
            id_to_tester = {int(t.alias): t for t in shared.factor_testers}
            shared.factor_testers = [id_to_tester[i] for i in new_order if i in id_to_tester]
            assert len(shared.factor_testers) == n, "Reordered list length mismatch"
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@shared_bp.route('/delete_submission', methods=['POST'])
def delete_submission():
    data = request.get_json()
    id_time = data.get('id_time')
    try:
        with _factor_testers_lock:
            n = len(shared.factor_testers)
            tester = next((t for t in shared.factor_testers if t.alias == str(id_time)), None)
            assert tester is not None, "Submission not found"
            tester.delete()
            shared.factor_testers = [t for t in shared.factor_testers if t.alias != str(id_time)]
            assert len(shared.factor_testers) == n - 1, "No submission deleted"
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@shared_bp.route('/clear_all_submissions', methods=['POST'])
def clear_all_submissions():
    try:
        with _factor_testers_lock:
            for tester in shared.factor_testers:
                try:
                    tester.delete()
                except Exception:
                    pass
            shared.factor_testers = []
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@shared_bp.route('/delete_path_of_submission', methods=['POST'])
def delete_path_of_submission():
    data = request.get_json()
    id_time   = data.get('id_time')
    new_paths = data.get('new_paths')
    try:
        with _factor_testers_lock:
            tester = next((t for t in shared.factor_testers if t.alias == str(id_time)), None)
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
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
