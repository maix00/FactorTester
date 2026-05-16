"""Time template routes."""

from flask import jsonify, request

from server.modules.templates import templates_bp
from server.modules.templates.common import load_template_list, new_template_id, save_template_list
from server.services.http_auth import login_required
from server.services.runtime_state import get_user_file_lock, require_user


@templates_bp.route('/api/time_templates', methods=['GET'])
@login_required
def list_time_templates():
    username = require_user()
    with get_user_file_lock(username):
        templates = load_template_list(username, 'time')
    return jsonify({'success': True, 'templates': [{'id': t['id'], 'name': t['name']} for t in templates]})


@templates_bp.route('/api/time_templates', methods=['POST'])
@login_required
def save_time_template():
    data = request.get_json()
    name = (data.get('name') or '').strip()
    time_data = data.get('time_data', {})
    if not name:
        return jsonify({'success': False, 'error': '模板名称不能为空'})
    if not isinstance(time_data, dict) or not time_data:
        return jsonify({'success': False, 'error': '时间数据不能为空'})
    username = require_user()
    with get_user_file_lock(username):
        templates = load_template_list(username, 'time')
        template_id = new_template_id()
        templates.append({'id': template_id, 'name': name, 'time_data': time_data})
        save_template_list(username, 'time', templates)
    return jsonify({'success': True, 'id': template_id})


@templates_bp.route('/api/time_templates/<tpl_id>', methods=['GET'])
@login_required
def get_time_template(tpl_id):
    username = require_user()
    with get_user_file_lock(username):
        templates = load_template_list(username, 'time')
    template = next((t for t in templates if t['id'] == tpl_id), None)
    if not template:
        return jsonify({'success': False, 'error': '模板不存在'}), 404
    return jsonify({'success': True, 'template': template})


@templates_bp.route('/api/time_templates/<tpl_id>', methods=['PUT'])
@login_required
def update_time_template(tpl_id):
    data = request.get_json()
    username = require_user()
    with get_user_file_lock(username):
        templates = load_template_list(username, 'time')
        template = next((t for t in templates if t['id'] == tpl_id), None)
        if not template:
            return jsonify({'success': False, 'error': '模板不存在'}), 404
        if 'name' in data:
            name = data['name'].strip()
            if not name:
                return jsonify({'success': False, 'error': '模板名称不能为空'})
            template['name'] = name
        if 'time_data' in data:
            if not isinstance(data['time_data'], dict) or not data['time_data']:
                return jsonify({'success': False, 'error': '时间数据不能为空'})
            template['time_data'] = data['time_data']
        save_template_list(username, 'time', templates)
    return jsonify({'success': True})


@templates_bp.route('/api/time_templates/<tpl_id>', methods=['DELETE'])
@login_required
def delete_time_template(tpl_id):
    username = require_user()
    with get_user_file_lock(username):
        templates = load_template_list(username, 'time')
        before = len(templates)
        templates = [t for t in templates if t['id'] != tpl_id]
        if len(templates) == before:
            return jsonify({'success': False, 'error': '模板不存在'}), 404
        save_template_list(username, 'time', templates)
    return jsonify({'success': True})
