"""Parameter template and current-parameter routes."""

import pandas as pd
from flask import jsonify, request

from server.modules.templates import templates_bp
from server.services.api_response import api_ok, route_guard
from server.modules.templates.common import build_factor_rows, load_template_list, new_template_id, save_template_list
from server.services.accounts import account_display_name, can_view_user_scope, visible_accounts_for
from server.services.factor_registry import get_factor_family_instance
from server.services.http_auth import login_required
from server.services.runtime_state import get_session_params, get_user_file_lock, require_user, save_session_params


@templates_bp.route('/api/params_templates/<ff_alias>', methods=['GET'])
@login_required
def list_params_templates(ff_alias):
    username = require_user()
    include_visible = request.args.get('include_visible') == '1'
    accounts = visible_accounts_for(username, include_self=True) if include_visible else [{'username': username, 'alias': username}]
    current_account = next((a for a in accounts if a.get('username') == username), None) or {}
    can_filter_organization = bool(current_account.get('role') == 'super_admin' or current_account.get('is_admin'))
    result = []
    for account in accounts:
        owner = account.get('username')
        if not owner:
            continue
        with get_user_file_lock(owner):
            templates = load_template_list(owner, 'params', ff_alias)
        for template in templates:
            result.append({
                'id': template['id'],
                'name': template['name'],
                'owner_username': owner,
                'owner_alias': account_display_name(account),
                'owner_organization_id': account.get('organization_id') or '',
                'owner_organization_name': account.get('organization_name') or '',
                'editable': owner == username,
            })
    return jsonify({
        'success': True,
        'templates': result,
        'can_filter_organization': can_filter_organization,
    })


@templates_bp.route('/api/params_templates/<ff_alias>', methods=['POST'])
@login_required
def save_params_template(ff_alias):
    data = request.get_json()
    name = (data.get('name') or '').strip()
    params_list = data.get('params_list', [])
    if not name:
        return jsonify({'success': False, 'error': '模板名称不能为空'})
    if not isinstance(params_list, list) or len(params_list) == 0:
        return jsonify({'success': False, 'error': '参数列表不能为空'})
    username = require_user()
    with get_user_file_lock(username):
        templates = load_template_list(username, 'params', ff_alias)
        template_id = new_template_id()
        templates.append({'id': template_id, 'name': name, 'params_list': params_list})
        save_template_list(username, 'params', templates, ff_alias)
    return jsonify({'success': True, 'id': template_id})


@templates_bp.route('/api/params_templates/<ff_alias>/<tpl_id>', methods=['GET'])
@login_required
def get_params_template(ff_alias, tpl_id):
    username = require_user()
    owner_username = (request.args.get('owner_username') or username).strip()
    if not can_view_user_scope(username, owner_username):
        return jsonify({'success': False, 'error': '无权查看该用户配置'}), 403
    with get_user_file_lock(owner_username):
        templates = load_template_list(owner_username, 'params', ff_alias)
    template = next((t for t in templates if t['id'] == tpl_id), None)
    if not template:
        return jsonify({'success': False, 'error': '模板不存在'}), 404
    template = dict(template)
    template['owner_username'] = owner_username
    template['editable'] = owner_username == username
    return jsonify({'success': True, 'template': template})


@templates_bp.route('/api/params_templates/<ff_alias>/<tpl_id>', methods=['PUT'])
@login_required
def update_params_template(ff_alias, tpl_id):
    data = request.get_json()
    username = require_user()
    with get_user_file_lock(username):
        templates = load_template_list(username, 'params', ff_alias)
        template = next((t for t in templates if t['id'] == tpl_id), None)
        if not template:
            return jsonify({'success': False, 'error': '模板不存在'}), 404
        if 'name' in data:
            name = data['name'].strip()
            if not name:
                return jsonify({'success': False, 'error': '模板名称不能为空'})
            if template['name'].startswith('__global_'):
                return jsonify({'success': False, 'error': '设置快照关联参数模板不允许重命名'})
            template['name'] = name
        if 'params_list' in data:
            if not isinstance(data['params_list'], list) or len(data['params_list']) == 0:
                return jsonify({'success': False, 'error': '参数列表不能为空'})
            template['params_list'] = data['params_list']
        save_template_list(username, 'params', templates, ff_alias)
    return jsonify({'success': True})


@templates_bp.route('/api/params_templates/<ff_alias>/<tpl_id>', methods=['DELETE'])
@login_required
def delete_params_template(ff_alias, tpl_id):
    username = require_user()
    with get_user_file_lock(username):
        templates = load_template_list(username, 'params', ff_alias)
        before = len(templates)
        templates = [t for t in templates if t['id'] != tpl_id]
        if len(templates) == before:
            return jsonify({'success': False, 'error': '模板不存在'}), 404
        save_template_list(username, 'params', templates, ff_alias)
    return jsonify({'success': True})


def _serialize_params(params_list):
    result = []
    for params in params_list:
        item = {}
        for key, value in params.items():
            if isinstance(value, pd.Timedelta):
                item[key] = str(value)
            else:
                try:
                    item[key] = str(value) if not isinstance(value, (str, int, float, bool, type(None))) else value
                except Exception:
                    item[key] = repr(value)
        result.append(item)
    return result


@templates_bp.route('/api/current_params/<ff_alias>', methods=['GET'])
@login_required
@route_guard
def get_current_params(ff_alias):
    factor_family = get_factor_family_instance(ff_alias)
    params_list = get_session_params(ff_alias, factor_family)
    return api_ok({'params_list': _serialize_params(params_list)})


@templates_bp.route('/replace_params', methods=['POST'])
@login_required
@route_guard
def replace_params():
    data = request.get_json()
    ff_alias = data.get('factor_family_alias')
    params_list = data.get('params_list', [])
    factor_family = get_factor_family_instance(ff_alias)
    seen = set()
    new_params_list = []
    for params in params_list:
        factor_family._check_in_space(**params)
        new_params = {
            param.alias: param._value_space.rectify(params[param.alias])
            if param.alias in params
            else param.default_value
            for param in factor_family.params
        }
        key = tuple(str(new_params.get(param.alias, '')) for param in factor_family.params)
        if key not in seen:
            seen.add(key)
            new_params_list.append(new_params)
    save_session_params(ff_alias, new_params_list)
    return api_ok({'factor_rows': build_factor_rows(factor_family, new_params_list)})
