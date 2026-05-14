"""Routes for factor-library parameter configurations."""
from __future__ import annotations
from typing import cast

from flask import jsonify, request

from server.modules.custom_factors import cf_bp
from server.services.api_response import api_ok, route_guard
from server.modules.custom_factors.param_config_service import (
    build_param_factor_overview,
    list_param_config_users,
    save_current_user_param_config,
)
from server.modules.custom_factors.param_config_store import (
    DEFAULT_SCOPE_KEY,
    delete_param_config,
    delete_scope,
    ensure_scope_exists,
    list_param_config_scopes,
    load_param_config,
    rename_scope,
)
from server.services.accounts import can_view_user_scope
from server.services.http_auth import login_required
from server.services.runtime_state import current_user, get_user_file_lock


def _username() -> str | None:
    u = current_user()
    if u is None:
        return None
    return u


@cf_bp.route('/api/param-factor-overview', methods=['GET'])
@login_required
def api_param_factor_overview():
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    include_subordinates = request.args.get('include_subordinates') == '1'
    scope_key = request.args.get('scope_key') or None
    payload = build_param_factor_overview(username, include_subordinates, scope_key=scope_key)
    return jsonify({'success': True, **payload})


@cf_bp.route('/api/param-configs/<ff_alias>', methods=['GET'])
@login_required
def api_param_configs(ff_alias):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    scope_key = request.args.get('scope_key', DEFAULT_SCOPE_KEY)
    payload = list_param_config_users(username, ff_alias, scope_key=scope_key)
    return jsonify({'success': True, **payload})


@cf_bp.route('/api/param-configs/<ff_alias>/<owner_username>', methods=['GET'])
@login_required
def api_get_param_config(ff_alias, owner_username):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    if not can_view_user_scope(username, owner_username):
        return jsonify({'success': False, 'error': '无权查看该用户配置'}), 403
    scope_key = request.args.get('scope_key', DEFAULT_SCOPE_KEY)
    config = load_param_config(owner_username, ff_alias, scope_key=scope_key)
    if not config:
        return jsonify({'success': False, 'error': '该用户尚未保存因子库参数配置'}), 404
    config = dict(config)
    config['owner_username'] = owner_username
    config['editable'] = owner_username == username
    return jsonify({'success': True, 'config': config})


@cf_bp.route('/api/param-configs/<ff_alias>', methods=['PUT'])
@login_required
@route_guard
def api_save_param_config(ff_alias):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    data = request.get_json() or {}
    params_list = data.get('params_list', [])
    scope_key = data.get('scope_key', DEFAULT_SCOPE_KEY)
    if not isinstance(params_list, list):
        return jsonify({'success': False, 'error': '参数列表格式无效'})
    with get_user_file_lock(username):
        config, factors = save_current_user_param_config(username, ff_alias, params_list, scope_key=scope_key)
    return api_ok({'config': config, 'factors': factors})


@cf_bp.route('/api/param-configs/<ff_alias>', methods=['DELETE'])
@login_required
def api_delete_param_config(ff_alias):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    scope_key = request.args.get('scope_key', DEFAULT_SCOPE_KEY)
    with get_user_file_lock(username):
        deleted = delete_param_config(username, ff_alias, scope_key=scope_key)
    if not deleted:
        return jsonify({'success': False, 'error': '配置不存在'}), 404
    return jsonify({'success': True})


# ── Scope management ──

@cf_bp.route('/api/param-config-scopes', methods=['GET'])
@login_required
def api_list_scopes():
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    scopes = list_param_config_scopes(username)
    return jsonify({'success': True, 'scopes': scopes})


@cf_bp.route('/api/param-config-scopes/<scope_key>', methods=['PUT'])
@login_required
def api_ensure_scope(scope_key):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    with get_user_file_lock(username):
        actual = ensure_scope_exists(username, scope_key)
    return jsonify({'success': True, 'scope_key': actual})


@cf_bp.route('/api/param-config-scopes/<scope_key>', methods=['PATCH'])
@login_required
def api_rename_scope(scope_key):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    data = request.get_json() or {}
    new_key = (data.get('new_scope_key') or '').strip()
    if not new_key:
        return jsonify({'success': False, 'error': '新 scope key 不能为空'})
    if new_key == scope_key:
        return jsonify({'success': True, 'scope_key': scope_key})
    with get_user_file_lock(username):
        ok = rename_scope(username, scope_key, new_key)
    if not ok:
        return jsonify({'success': False, 'error': '重命名失败，源 scope 不存在或目标已存在'}), 400
    return jsonify({'success': True, 'scope_key': new_key})


@cf_bp.route('/api/param-config-scopes/<scope_key>', methods=['DELETE'])
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
