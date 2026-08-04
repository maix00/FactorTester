"""Product group (产品组) REST routes.

Product groups are named collections of product paths, independent of path_templates.
A path_template can reference groups by name in its submissions.
"""
from flask import jsonify, request

from server.modules.templates import templates_bp
from server.modules.products.product_group_store import (
    change_product_group_subjects,
    create_product_group,
    delete_product_group,
    load_product_groups,
    product_group_subjects,
    rename_product_group,
    reorder_product_groups,
    update_product_group,
)
from server.modules.custom_factors.factor_library_store import rename_scope
from server.modules.custom_factors.factor_library_service import (
    build_factor_library_overview,
)
from server.modules.custom_factors.client_library import (
    build_client_library_projection,
)
from server.modules.custom_factors.factor_set_registry import factor_set_catalog
from server.services.http_auth import login_required
from server.services.session_runtime import require_user


# ── List / Create ──

@templates_bp.route('/api/product-groups', methods=['GET'])
@login_required
def list_product_groups():
    username = require_user()
    groups = load_product_groups(username)
    return jsonify({'success': True, 'groups': groups})


@templates_bp.route('/api/product-groups/resolve', methods=['POST'])
@login_required
def resolve_product_groups():
    data = request.get_json(silent=True) or {}
    ids = data.get('ids') or []
    if not isinstance(ids, list):
        return jsonify({'success': False, 'error': 'ids 必须是数组'}), 400
    wanted = {str(item).strip() for item in ids if str(item).strip()}
    username = require_user()
    matches = [
        group for group in load_product_groups(username)
        if str(group.get('id') or '').strip() in wanted
    ]
    return jsonify({'success': True, 'groups': matches})


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


@templates_bp.route('/api/product-groups/<group_id>/subjects', methods=['GET', 'POST'])
@login_required
def product_group_subjects_view(group_id):
    username = require_user()
    product_group_ref = f"product-group:{group_id}"
    try:
        if request.method == 'GET':
            value = product_group_subjects(username, product_group_ref)
        else:
            data = request.get_json(silent=True) or {}
            action = str(data.get('action') or '')
            factor_refs = data.get('factor_refs') or []
            factor_set_refs = data.get('factor_set_refs') or []
            if action == 'add':
                _validate_registered_subjects(
                    username,
                    factor_refs=factor_refs,
                    factor_set_refs=factor_set_refs,
                )
            value = change_product_group_subjects(
                username,
                product_group_ref,
                action=action,
                factor_refs=factor_refs,
                factor_set_refs=factor_set_refs,
            )
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    if value is None:
        return jsonify({'success': False, 'error': '产品组不存在'}), 404
    return jsonify({'success': True, 'subjects': value})


def _validate_registered_subjects(
    username: str,
    *,
    factor_refs: list[str],
    factor_set_refs: list[str],
) -> None:
    """Reject dangling additions while allowing stale bindings to be removed."""
    if not isinstance(factor_refs, list) or not all(
        isinstance(item, str) for item in factor_refs
    ):
        raise ValueError('factor_refs must be an array of references')
    if not isinstance(factor_set_refs, list) or not all(
        isinstance(item, str) for item in factor_set_refs
    ):
        raise ValueError('factor_set_refs must be an array of references')
    projection = build_client_library_projection(
        build_factor_library_overview(username, False),
        principal=username,
    )
    registered_factors = {
        str(item.get('factor_ref') or '')
        for item in projection.get('factors') or []
    }
    registered_sets = {
        str(item.get('set_ref') or '')
        for item in factor_set_catalog(username)
    }
    missing_factors = sorted(set(factor_refs) - registered_factors)
    missing_sets = sorted(set(factor_set_refs) - registered_sets)
    if missing_factors:
        raise ValueError(
            '绑定前必须先注册因子: ' + ', '.join(missing_factors)
        )
    if missing_sets:
        raise ValueError(
            '绑定前必须先同步因子集合: ' + ', '.join(missing_sets)
        )


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
    rename_scope(username, name, new_name)
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
