"""Routes for factor-library parameter configurations."""
from __future__ import annotations

from flask import jsonify, request

from server.modules.custom_factors import factor_library_internal_bp
from server.modules.custom_factors.factor_library_service import (
    build_factor_library_overview,
    delete_factor_library_factor,
    list_factor_library_config_users,
    list_factor_library_product_groups,
    save_current_user_library_config,
)
from server.modules.custom_factors.factor_library_store import (
    DEFAULT_SCOPE_KEY,
    delete_factor_param_config,
    delete_scope,
    ensure_scope_exists,
    load_factor_param_config,
    normalize_product_group,
    rename_scope,
)
from server.services.api_response import api_ok, route_guard
from server.services.factor_registry import get_factor_family_instance
from server.services.http_auth import login_required
from server.services.session_runtime import current_user, get_user_file_lock
from tools.data.account_manage import can_view_user_scope


def _username() -> str | None:
    u = current_user()
    if u is None:
        return None
    return u


@factor_library_internal_bp.route('/overview', methods=['GET'])
@login_required
def api_factor_library_overview():
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    include_subordinates = request.args.get('include_subordinates') == '1'
    product_group = request.args.get('product_group') or request.args.get('scope_key') or None
    factor_family_alias = request.args.get('factor_family_alias') or None
    payload = build_factor_library_overview(username, include_subordinates, product_group=product_group, factor_family_alias=factor_family_alias)
    return jsonify({'success': True, **payload})


@factor_library_internal_bp.route('/configurations/<ff_alias>', methods=['GET'])
@login_required
def api_factor_library_configs(ff_alias):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    product_group = request.args.get('product_group') or request.args.get('scope_key') or DEFAULT_SCOPE_KEY
    payload = list_factor_library_config_users(username, ff_alias, product_group=product_group)
    return jsonify({'success': True, **payload})


@factor_library_internal_bp.route('/configurations/<ff_alias>/<owner_username>', methods=['GET'])
@login_required
def api_get_factor_library_config(ff_alias, owner_username):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    if not can_view_user_scope(username, owner_username):
        return jsonify({'success': False, 'error': '无权查看该用户配置'}), 403
    product_group = request.args.get('product_group') or request.args.get('scope_key') or DEFAULT_SCOPE_KEY
    config = load_factor_param_config(owner_username, ff_alias, scope_key=product_group)
    if not config:
        return jsonify({'success': False, 'error': '该用户尚未保存因子库参数配置'}), 404
    config = dict(config)
    config['owner_username'] = owner_username
    config['editable'] = owner_username == username
    return jsonify({'success': True, 'config': config})


@factor_library_internal_bp.route('/configurations/<ff_alias>', methods=['PUT'])
@login_required
@route_guard
def api_save_factor_library_config(ff_alias):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    data = request.get_json() or {}
    params_list = data.get('params_list', [])
    product_group = data.get('product_group') or data.get('scope_key') or DEFAULT_SCOPE_KEY
    metadata = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}
    for key in ('note', 'research_report', 'product_group_paths'):
        if key in data and key not in metadata:
            metadata[key] = data.get(key)
    if not isinstance(params_list, list):
        return jsonify({'success': False, 'error': '参数列表格式无效'})
    with get_user_file_lock(username):
        config, factors = save_current_user_library_config(
            username,
            ff_alias,
            params_list,
            product_group=product_group,
            metadata=metadata,
        )
    return api_ok({'config': config, 'factors': factors})


@factor_library_internal_bp.route('/configurations/<ff_alias>', methods=['DELETE'])
@login_required
def api_delete_factor_library_config(ff_alias):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    scope_key = request.args.get('product_group') or request.args.get('scope_key') or DEFAULT_SCOPE_KEY
    factor_alias = str(request.args.get('factor_alias') or '').strip()
    with get_user_file_lock(username):
        deleted = (
            delete_factor_library_factor(
                username, ff_alias, factor_alias, product_group=scope_key,
            )
            if factor_alias else delete_factor_param_config(
                username, ff_alias, scope_key=scope_key,
            )
        )
    if not deleted:
        return jsonify({'success': False, 'error': '因子或配置不存在'}), 404
    return jsonify({'success': True})


@factor_library_internal_bp.route('/configurations/<ff_alias>/factors', methods=['POST'])
@login_required
def api_add_factor_to_library_config(ff_alias):
    """从当前会话参数中，将一个因子追加到用户因子库配置中。"""
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    data = request.get_json() or {}
    factor_alias = (data.get('factor_alias') or '').strip()
    product_group = data.get('product_group') or data.get('scope_key') or DEFAULT_SCOPE_KEY
    scope_key = normalize_product_group(product_group)
    if not factor_alias:
        return jsonify({'success': False, 'error': '缺少 factor_alias'}), 400

    # 从 page_factors 查找因子（因子是唯一数据源），提取其参数行。
    page_uuid = str(data.get('page_uuid') or '')
    try:
        factor_family = get_factor_family_instance(ff_alias, username=username)
    except ImportError:
        return jsonify({'success': False, 'error': f'因子族 {ff_alias} 不存在'}), 404

    matched_param = None
    if page_uuid:
        from server.services.factor_registry import page_factors
        factor = page_factors.get(page_uuid, {}).get(factor_alias)
        if factor is not None:
            matched_param = {
                p.alias: getattr(factor, p.alias, p.default_value)
                for p in factor_family.params
            }

    if matched_param is None:
        return jsonify({'success': False, 'error': f'未找到因子 {factor_alias} 对应的参数'}), 404

    # 读取当前 scope 下的已有配置，追加新参数行（去重）
    with get_user_file_lock(username):
        existing_config = load_factor_param_config(username, ff_alias, scope_key=scope_key)
        existing_params = existing_config.get('params_list', []) if existing_config else []

        # 去重：检查是否已存在相同因子 alias 的参数行
        existing_aliases = set()
        for row in existing_params:
            row_alias = factor_family.get_alias(**row)
            if row_alias:
                existing_aliases.add(row_alias)

        if factor_alias in existing_aliases:
            return jsonify({'success': True, 'message': f'因子 {factor_alias} 已存在，无需重复添加', 'skipped': True})

        existing_params.append(matched_param)
        config, factors = save_current_user_library_config(username, ff_alias, existing_params, product_group=scope_key)

    return api_ok({'config': config, 'factors': factors})


# ── Scope management ──

@factor_library_internal_bp.route('/configuration-scopes', methods=['GET'])
@login_required
def api_list_scopes():
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    product_groups = list_factor_library_product_groups(username)
    return jsonify({'success': True, 'scopes': product_groups, 'product_groups': product_groups})


@factor_library_internal_bp.route('/configuration-scopes/<scope_key>', methods=['PUT'])
@login_required
def api_ensure_scope(scope_key):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    with get_user_file_lock(username):
        actual = ensure_scope_exists(username, scope_key)
    return jsonify({'success': True, 'scope_key': actual, 'product_group': actual})


@factor_library_internal_bp.route('/configuration-scopes/<scope_key>', methods=['PATCH'])
@login_required
def api_rename_scope(scope_key):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    data = request.get_json() or {}
    new_key = (data.get('new_product_group') or data.get('new_scope_key') or '').strip()
    if not new_key:
        return jsonify({'success': False, 'error': '新 scope key 不能为空'})
    if new_key == scope_key:
        return jsonify({'success': True, 'scope_key': scope_key, 'product_group': scope_key})
    with get_user_file_lock(username):
        ok = rename_scope(username, scope_key, new_key)
    if not ok:
        return jsonify({'success': False, 'error': '重命名失败，源 scope 不存在或目标已存在'}), 400
    return jsonify({'success': True, 'scope_key': new_key, 'product_group': new_key})


@factor_library_internal_bp.route('/configuration-scopes/<scope_key>', methods=['DELETE'])
@login_required
def api_delete_scope(scope_key):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    with get_user_file_lock(username):
        ok = delete_scope(username, scope_key)
    if not ok:
        return jsonify({'success': False, 'error': '无法删除默认或不存在'}), 400
    return jsonify({'success': True})
