"""
Templates Blueprint: CRUD for path / time / params templates,
plus current_params and replace_params endpoints.
"""
from flask import Blueprint, request, jsonify
from .shared import (
    _require_user, _get_user_file_lock,
    _load_user_tpls, _save_user_tpls, _new_tpl_id,
    login_required,
    get_factor_family_instance, _get_session_params, _save_session_params,
)

templates_bp = Blueprint('templates', __name__)

# ── 路径模板 ──────────────────────────────────────────────────────────────────

@templates_bp.route('/api/path_templates', methods=['GET'])
@login_required
def list_path_templates():
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'path')
    return jsonify({'success': True, 'templates': [{'id': t['id'], 'name': t['name']} for t in templates]})


@templates_bp.route('/api/path_templates', methods=['POST'])
@login_required
def save_path_template():
    data = request.get_json()
    name = (data.get('name') or '').strip()
    submissions = data.get('submissions', [])
    if not name:
        return jsonify({'success': False, 'error': '模板名称不能为空'})
    if not isinstance(submissions, list) or len(submissions) == 0:
        return jsonify({'success': False, 'error': '提交列表不能为空'})
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'path')
        new_id = _new_tpl_id()
        templates.append({'id': new_id, 'name': name, 'submissions': submissions})
        _save_user_tpls(u, 'path', templates)
    return jsonify({'success': True, 'id': new_id})


@templates_bp.route('/api/path_templates/<tpl_id>', methods=['GET'])
@login_required
def get_path_template(tpl_id):
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'path')
    tpl = next((t for t in templates if t['id'] == tpl_id), None)
    if not tpl:
        return jsonify({'success': False, 'error': '模板不存在'}), 404
    return jsonify({'success': True, 'template': tpl})


@templates_bp.route('/api/path_templates/<tpl_id>', methods=['PUT'])
@login_required
def update_path_template(tpl_id):
    data = request.get_json()
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'path')
        tpl = next((t for t in templates if t['id'] == tpl_id), None)
        if not tpl:
            return jsonify({'success': False, 'error': '模板不存在'}), 404
        if 'name' in data:
            name = data['name'].strip()
            if not name:
                return jsonify({'success': False, 'error': '模板名称不能为空'})
            tpl['name'] = name
        if 'submissions' in data:
            if not isinstance(data['submissions'], list) or len(data['submissions']) == 0:
                return jsonify({'success': False, 'error': '提交列表不能为空'})
            tpl['submissions'] = data['submissions']
        _save_user_tpls(u, 'path', templates)
    return jsonify({'success': True})


@templates_bp.route('/api/path_templates/<tpl_id>', methods=['DELETE'])
@login_required
def delete_path_template(tpl_id):
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'path')
        before = len(templates)
        templates = [t for t in templates if t['id'] != tpl_id]
        if len(templates) == before:
            return jsonify({'success': False, 'error': '模板不存在'}), 404
        _save_user_tpls(u, 'path', templates)
    return jsonify({'success': True})

# ── 时间模板 ──────────────────────────────────────────────────────────────────

@templates_bp.route('/api/time_templates', methods=['GET'])
@login_required
def list_time_templates():
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'time')
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
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'time')
        new_id = _new_tpl_id()
        templates.append({'id': new_id, 'name': name, 'time_data': time_data})
        _save_user_tpls(u, 'time', templates)
    return jsonify({'success': True, 'id': new_id})


@templates_bp.route('/api/time_templates/<tpl_id>', methods=['GET'])
@login_required
def get_time_template(tpl_id):
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'time')
    tpl = next((t for t in templates if t['id'] == tpl_id), None)
    if not tpl:
        return jsonify({'success': False, 'error': '模板不存在'}), 404
    return jsonify({'success': True, 'template': tpl})


@templates_bp.route('/api/time_templates/<tpl_id>', methods=['PUT'])
@login_required
def update_time_template(tpl_id):
    data = request.get_json()
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'time')
        tpl = next((t for t in templates if t['id'] == tpl_id), None)
        if not tpl:
            return jsonify({'success': False, 'error': '模板不存在'}), 404
        if 'name' in data:
            name = data['name'].strip()
            if not name:
                return jsonify({'success': False, 'error': '模板名称不能为空'})
            tpl['name'] = name
        if 'time_data' in data:
            if not isinstance(data['time_data'], dict) or not data['time_data']:
                return jsonify({'success': False, 'error': '时间数据不能为空'})
            tpl['time_data'] = data['time_data']
        _save_user_tpls(u, 'time', templates)
    return jsonify({'success': True})


@templates_bp.route('/api/time_templates/<tpl_id>', methods=['DELETE'])
@login_required
def delete_time_template(tpl_id):
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'time')
        before = len(templates)
        templates = [t for t in templates if t['id'] != tpl_id]
        if len(templates) == before:
            return jsonify({'success': False, 'error': '模板不存在'}), 404
        _save_user_tpls(u, 'time', templates)
    return jsonify({'success': True})

# ── 参数模板 ──────────────────────────────────────────────────────────────────

@templates_bp.route('/api/params_templates/<ff_alias>', methods=['GET'])
@login_required
def list_params_templates(ff_alias):
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'params', ff_alias)
    return jsonify({'success': True, 'templates': [{'id': t['id'], 'name': t['name']} for t in templates]})


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
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'params', ff_alias)
        new_id = _new_tpl_id()
        templates.append({'id': new_id, 'name': name, 'params_list': params_list})
        _save_user_tpls(u, 'params', templates, ff_alias)
    return jsonify({'success': True, 'id': new_id})


@templates_bp.route('/api/params_templates/<ff_alias>/<tpl_id>', methods=['GET'])
@login_required
def get_params_template(ff_alias, tpl_id):
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'params', ff_alias)
    tpl = next((t for t in templates if t['id'] == tpl_id), None)
    if not tpl:
        return jsonify({'success': False, 'error': '模板不存在'}), 404
    return jsonify({'success': True, 'template': tpl})


@templates_bp.route('/api/params_templates/<ff_alias>/<tpl_id>', methods=['PUT'])
@login_required
def update_params_template(ff_alias, tpl_id):
    data = request.get_json()
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'params', ff_alias)
        tpl = next((t for t in templates if t['id'] == tpl_id), None)
        if not tpl:
            return jsonify({'success': False, 'error': '模板不存在'}), 404
        if 'name' in data:
            name = data['name'].strip()
            if not name:
                return jsonify({'success': False, 'error': '模板名称不能为空'})
            tpl['name'] = name
        if 'params_list' in data:
            if not isinstance(data['params_list'], list) or len(data['params_list']) == 0:
                return jsonify({'success': False, 'error': '参数列表不能为空'})
            tpl['params_list'] = data['params_list']
        _save_user_tpls(u, 'params', templates, ff_alias)
    return jsonify({'success': True})


@templates_bp.route('/api/params_templates/<ff_alias>/<tpl_id>', methods=['DELETE'])
@login_required
def delete_params_template(ff_alias, tpl_id):
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'params', ff_alias)
        before = len(templates)
        templates = [t for t in templates if t['id'] != tpl_id]
        if len(templates) == before:
            return jsonify({'success': False, 'error': '模板不存在'}), 404
        _save_user_tpls(u, 'params', templates, ff_alias)
    return jsonify({'success': True})

# ── 当前参数 & 批量替换 ────────────────────────────────────────────────────────

@templates_bp.route('/api/current_params/<ff_alias>', methods=['GET'])
@login_required
def get_current_params(ff_alias):
    try:
        ff = get_factor_family_instance(ff_alias)
        params_list = _get_session_params(ff_alias, ff)
        return jsonify({'success': True, 'params_list': params_list})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@templates_bp.route('/replace_params', methods=['POST'])
@login_required
def replace_params():
    data = request.get_json()
    ff_alias = data.get('factor_family_alias')
    params_list = data.get('params_list', [])
    try:
        ff = get_factor_family_instance(ff_alias)
        new_pl = []
        for params in params_list:
            ff._check_in_space(**params)
            new_params = {p.alias: p.rectify_value(params[p.alias]) if p.alias in params else p.default_value for p in ff.params}
            new_pl.append(new_params)
        _save_session_params(ff_alias, new_pl)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── 全局模板 ──────────────────────────────────────────────────────────────────

@templates_bp.route('/api/global_templates', methods=['GET'])
@login_required
def list_global_templates():
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'global')
    return jsonify({'success': True, 'templates': [{'id': t['id'], 'name': t['name'], 'ff_alias': t.get('ff_alias', '')} for t in templates]})


@templates_bp.route('/api/global_templates', methods=['POST'])
@login_required
def save_global_template():
    data = request.get_json()
    name = (data.get('name') or '').strip()
    ff_alias = (data.get('ff_alias') or '').strip()
    snapshot = data.get('snapshot', {})
    if not name:
        return jsonify({'success': False, 'error': '模板名称不能为空'})
    if not ff_alias:
        return jsonify({'success': False, 'error': '因子家族不能为空'})
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'global')
        new_id = _new_tpl_id()
        templates.append({
            'id': new_id,
            'name': name,
            'ff_alias': ff_alias,
            'snapshot': snapshot,  # { params_list, time_data, submissions, return_freqs, group_settings }
        })
        _save_user_tpls(u, 'global', templates)
    return jsonify({'success': True, 'id': new_id})


@templates_bp.route('/api/global_templates/<tpl_id>', methods=['GET'])
@login_required
def get_global_template(tpl_id):
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'global')
    tpl = next((t for t in templates if t['id'] == tpl_id), None)
    if not tpl:
        return jsonify({'success': False, 'error': '模板不存在'}), 404
    return jsonify({'success': True, 'template': tpl})


@templates_bp.route('/api/global_templates/<tpl_id>', methods=['PUT'])
@login_required
def update_global_template(tpl_id):
    data = request.get_json()
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'global')
        tpl = next((t for t in templates if t['id'] == tpl_id), None)
        if not tpl:
            return jsonify({'success': False, 'error': '模板不存在'}), 404
        if 'name' in data:
            name = data['name'].strip()
            if not name:
                return jsonify({'success': False, 'error': '模板名称不能为空'})
            tpl['name'] = name
        if 'snapshot' in data:
            tpl['snapshot'] = data['snapshot']
        _save_user_tpls(u, 'global', templates)
    return jsonify({'success': True})


@templates_bp.route('/api/global_templates/<tpl_id>', methods=['DELETE'])
@login_required
def delete_global_template(tpl_id):
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'global')
        before = len(templates)
        templates = [t for t in templates if t['id'] != tpl_id]
        if len(templates) == before:
            return jsonify({'success': False, 'error': '模板不存在'}), 404
        _save_user_tpls(u, 'global', templates)
    return jsonify({'success': True})
