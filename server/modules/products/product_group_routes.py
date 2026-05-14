"""Product group (产品组) REST routes.

Product groups are named collections of product paths, independent of path_templates.
A path_template can reference groups by name in its submissions.
"""
from flask import jsonify, request

from server.modules.templates import templates_bp
from server.modules.products.product_group_store import (
    create_product_group,
    delete_product_group,
    load_product_groups,
    rename_product_group,
    reorder_product_groups,
    update_product_group,
)
from server.services.http_auth import login_required
from server.services.runtime_state import require_user


# ── List / Create ──

@templates_bp.route('/api/product-groups', methods=['GET'])
@login_required
def list_product_groups():
    username = require_user()
    groups = load_product_groups(username)
    return jsonify({'success': True, 'groups': groups})


@templates_bp.route('/api/product-groups', methods=['POST'])
@login_required
def create_product_group_view():
    data = request.get_json()
    name = (data.get('name') or '').strip()
    paths = data.get('paths', [])
    if not name:
        return jsonify({'success': False, 'error': '产品组名称不能为空'}), 400
    if not isinstance(paths, list) or len(paths) == 0:
        return jsonify({'success': False, 'error': '请选择至少一个品种路径'}), 400
    username = require_user()
    group = create_product_group(username, name, paths)
    if group is None:
        return jsonify({'success': False, 'error': '产品组名称已存在'}), 409
    return jsonify({'success': True, 'group': group})


# ── Get / Update / Delete by name ──

@templates_bp.route('/api/product-groups/<name>', methods=['GET'])
@login_required
def get_product_group(name):
    username = require_user()
    groups = load_product_groups(username)
    for g in groups:
        if g.get('name') == name:
            return jsonify({'success': True, 'group': g})
    return jsonify({'success': False, 'error': '产品组不存在'}), 404


@templates_bp.route('/api/product-groups/<name>', methods=['PUT'])
@login_required
def update_product_group_view(name):
    data = request.get_json()
    paths = data.get('paths')
    username = require_user()
    group = update_product_group(username, name, paths=paths)
    if group is None:
        return jsonify({'success': False, 'error': '产品组不存在'}), 404
    return jsonify({'success': True, 'group': group})


@templates_bp.route('/api/product-groups/<name>', methods=['DELETE'])
@login_required
def delete_product_group_view(name):
    username = require_user()
    ok = delete_product_group(username, name)
    if not ok:
        return jsonify({'success': False, 'error': '产品组不存在'}), 404
    return jsonify({'success': True})


# ── Rename ──

@templates_bp.route('/api/product-groups/<name>/rename', methods=['PUT'])
@login_required
def rename_product_group_view(name):
    data = request.get_json()
    new_name = (data.get('name') or '').strip()
    if not new_name:
        return jsonify({'success': False, 'error': '新名称不能为空'}), 400
    username = require_user()
    group = rename_product_group(username, name, new_name)
    if group is None:
        return jsonify({'success': False, 'error': '重命名失败：名称已存在或产品组不存在'}), 400
    return jsonify({'success': True, 'group': group})


# ── Reorder ──

@templates_bp.route('/api/product-groups/reorder', methods=['PUT'])
@login_required
def reorder_product_groups_view():
    data = request.get_json()
    names = data.get('names', [])
    if not isinstance(names, list) or len(names) == 0:
        return jsonify({'success': False, 'error': 'names 不能为空'}), 400
    username = require_user()
    ok = reorder_product_groups(username, names)
    if not ok:
        return jsonify({'success': False, 'error': '排序失败：部分产品组不存在'}), 400
    return jsonify({'success': True})
