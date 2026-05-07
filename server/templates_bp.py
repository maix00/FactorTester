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
            if tpl['name'].startswith('__global_'):
                return jsonify({'success': False, 'error': '全局模板不允许重命名'})
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
        # 将 Timedelta/Arrow 等不可 JSON 序列化的值转为字符串
        import pandas as pd
        def _serialize_params(pl):
            result = []
            for params in pl:
                item = {}
                for k, v in params.items():
                    if isinstance(v, pd.Timedelta):
                        item[k] = str(v)
                    else:
                        try:
                            item[k] = str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v
                        except Exception:
                            item[k] = repr(v)
                result.append(item)
            return result
        return jsonify({'success': True, 'params_list': _serialize_params(params_list)})
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
        seen = set()
        new_pl = []
        for params in params_list:
            ff._check_in_space(**params)
            new_params = {p.alias: p._value_space.rectify(params[p.alias]) if p.alias in params else p.default_value for p in ff.params}
            # 去重：将参数值转为可哈希的 tuple 来判断是否重复
            key = tuple(str(new_params.get(p.alias, '')) for p in ff.params)
            if key not in seen:
                seen.add(key)
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
    """从快照构建可读摘要，展示各模块的具体值（类似外部摘要行）"""
    summary = {}

    # ── 时间范围 ──
    td = snap.get('time_data', {})
    if td:
        s_date = td.get('start_date') or td.get('start') or ''
        s_time = td.get('start_time', '')
        e_date = td.get('end_date') or td.get('end') or ''
        e_time = td.get('end_time', '')
        parts = [s_date]
        if s_time:
            parts.append(' ' + s_time)
        parts.append(' ~ ')
        parts.append(e_date)
        if e_time:
            parts.append(' ' + e_time)
        suffix = ''
        if td.get('is_trading_day'):
            suffix = ' (交易日)'
        elif td.get('is_cn_futures_day'):
            suffix = ' (期货日盘)'
        elif td.get('is_cn_futures_night'):
            suffix = ' (期货夜盘)'
        summary['time_range'] = ''.join(parts) + suffix

    # ── 参数列表 ── 每组参数单独展示具体值
    params = snap.get('params_list', [])
    if params:
        # 兼容旧格式 [{factor_name, params}, ...]
        if params[0] and 'params' in params[0]:
            params = [p.get('params', {}) for p in params]
        param_items = []
        for i, p in enumerate(params):
            if not p:
                continue
            pairs = [f"{k}={v}" for k, v in sorted(p.items())]
            if len(params) > 1:
                param_items.append(f"#{i+1}: " + ', '.join(pairs))
            else:
                param_items.append(', '.join(pairs))
        if param_items:
            summary['params'] = param_items

    # ── 品种分类 ── 展示每个提交的label和实际品种数（优先用 count_desc）
    subs = snap.get('submissions', [])
    if subs:
        sub_items = []
        for s in subs:
            label = s.get('label', '')
            count_desc = s.get('count_desc', '')
            if label and count_desc:
                sub_items.append(f"{label}({count_desc})")
            elif label:
                sub_items.append(label)
            elif count_desc:
                sub_items.append(count_desc)
        if sub_items:
            summary['products'] = sub_items

    # ── 收益率频率 ── 展示每个因子的频率设置
    freqs = snap.get('return_freqs', [])
    if freqs:
        freq_items = []
        for f in freqs:
            if f.get('checked') is False:
                continue
            alias = f.get('alias', '?')
            rf = f.get('return_freq', '')
            if rf:
                freq_items.append(f"{alias}:{rf}")
            else:
                freq_items.append(f"{alias}(默认)")
        if freq_items:
            summary['return_freqs'] = freq_items

    # ── 分组测试 ── 展示具体的分组设置
    gs = snap.get('group_settings', {})
    if gs:
        g_parts = []
        gc = gs.get('group_count', '')
        if gc:
            g_parts.append(f"分组数={gc}")
        fee_mode = gs.get('fee_mode', '')
        if fee_mode and fee_mode != 'none':
            fee_labels = {'none': '无', 'percent': '百分比', 'fixed': '固定'}
            g_parts.append(f"费率={fee_labels.get(fee_mode, fee_mode)}")
            if gs.get('fee_rate'):
                g_parts.append(f"{gs['fee_rate']}%")
        if gs.get('use_closetoday'):
            g_parts.append('平今')
        # 分组时间范围
        gs_start = '-'.join(filter(None, [
            gs.get('group_start_year', ''),
            str(gs.get('group_start_month', '')).zfill(2) if gs.get('group_start_month') else '',
            str(gs.get('group_start_day', '')).zfill(2) if gs.get('group_start_day') else '',
        ]))
        gs_end = '-'.join(filter(None, [
            gs.get('group_end_year', ''),
            str(gs.get('group_end_month', '')).zfill(2) if gs.get('group_end_month') else '',
            str(gs.get('group_end_day', '')).zfill(2) if gs.get('group_end_day') else '',
        ]))
        if gs_start and gs_end:
            g_parts.append(f"{gs_start} ~ {gs_end}")
        elif gs_start:
            g_parts.append(f"起始={gs_start}")
        elif gs_end:
            g_parts.append(f"终末={gs_end}")
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
