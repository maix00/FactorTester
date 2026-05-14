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
from server.modules.custom_factors.param_config_store import delete_param_config, load_param_config
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
    payload = build_param_factor_overview(username, include_subordinates)
    return jsonify({'success': True, **payload})


@cf_bp.route('/api/param-configs/<ff_alias>', methods=['GET'])
@login_required
def api_param_configs(ff_alias):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    payload = list_param_config_users(username, ff_alias)
    return jsonify({'success': True, **payload})


@cf_bp.route('/api/param-configs/<ff_alias>/<owner_username>', methods=['GET'])
@login_required
def api_get_param_config(ff_alias, owner_username):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    if not can_view_user_scope(username, owner_username):
        return jsonify({'success': False, 'error': '无权查看该用户配置'}), 403
    config = load_param_config(owner_username, ff_alias)
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
    if not isinstance(params_list, list):
        return jsonify({'success': False, 'error': '参数列表格式无效'})
    with get_user_file_lock(username):
        config, factors = save_current_user_param_config(username, ff_alias, params_list)
    return api_ok({'config': config, 'factors': factors})


@cf_bp.route('/api/param-configs/<ff_alias>', methods=['DELETE'])
@login_required
def api_delete_param_config(ff_alias):
    username = _username()
    if username is None:
        return jsonify({'success': False, 'error': '未登录'}), 401
    with get_user_file_lock(username):
        deleted = delete_param_config(username, ff_alias)
    if not deleted:
        return jsonify({'success': False, 'error': '配置不存在'}), 404
    return jsonify({'success': True})
