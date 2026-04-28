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
    result = []
    for t in templates:
        snap = t.get('snapshot', {})
        # 生成设置摘要
        summary = _build_snapshot_summary(snap)
        result.append({
            'id': t['id'],
            'name': t['name'],
            'ff_alias': t.get('ff_alias', ''),
            'summary': summary,
        })
    return jsonify({'success': True, 'templates': result})


def _build_snapshot_summary(snap: dict) -> dict:
    """从快照构建可读摘要"""
    summary = {}
    # 时间范围
    td = snap.get('time_data', {})
    if td:
        s = (td.get('start_date') or td.get('start') or '')
        e = (td.get('end_date') or td.get('end') or '')
        if s or e:
            summary['time_range'] = f"{s} ~ {e}"
    # 参数列表
    params = snap.get('params_list', [])
    if params:
        # 兼容旧格式
        if params[0] and 'params' in params[0]:
            params = [p.get('params', {}) for p in params]
        # 汇总所有参数（所有组共享的 key）
        all_keys = set()
        for p in params:
            all_keys.update(p.keys())
        if all_keys:
            # 取第一组的参数值作为展示
            first = params[0] if params else {}
            items = []
            for k in sorted(all_keys):
                v = first.get(k, '—')
                items.append(f"{k}={v}")
            summary['params'] = items[:8]  # 最多8个
            if len(all_keys) > 8:
                summary['params'].append(f'...共{len(all_keys)}个参数')
    # 品种分类
    subs = snap.get('submissions', [])
    if subs:
        paths_all = []
        for s in subs:
            paths_all.extend(s.get('paths', []))
        if paths_all:
            summary['products'] = f"{len(subs)}个提交, {len(paths_all)}个路径"
    # 收益率频率
    freqs = snap.get('return_freqs', [])
    if freqs:
        checked = [f for f in freqs if f.get('checked')]
        with_rf = [f for f in freqs if f.get('return_freq')]
        parts = []
        if checked:
            parts.append(f"{len(checked)}个因子选中")
        if with_rf:
            parts.append(f"{len(with_rf)}个设了频率")
        if parts:
            summary['return_freqs'] = ', '.join(parts)
    # 分组测试
    gs = snap.get('group_settings', {})
    if gs:
        g_parts = []
        if gs.get('group_count'):
            g_parts.append(f"分组数={gs['group_count']}")
        if gs.get('fee_mode') and gs['fee_mode'] != 'none':
            g_parts.append(f"费率模式={gs['fee_mode']}")
            if gs.get('fee_rate'):
                g_parts.append(f"费率={gs['fee_rate']}%")
        if g_parts:
            summary['group_test'] = ', '.join(g_parts)
    return summary


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
