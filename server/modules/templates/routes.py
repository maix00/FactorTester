"""
Templates Blueprint: CRUD for path / time / params templates,
plus current_params and replace_params endpoints.
"""
from flask import Blueprint, request, jsonify
from server.shared import (
    _require_user, _get_user_file_lock,
    login_required,
    get_factor_family_instance, _get_session_params, _save_session_params,
    _visible_accounts_for, _can_view_user_scope, _account_display_name,
)
from server.modules.shared.param_config import param_value_display
from server.services.user_storage import load_user_templates, new_template_id, save_user_templates


_load_user_tpls = load_user_templates
_save_user_tpls = save_user_templates
_new_tpl_id = new_template_id

templates_bp = Blueprint('templates', __name__)


def _build_factor_rows(ff, params_list):
    factors = ff.get_factors(params_list=params_list)
    rows = []
    for idx, (factor, row) in enumerate(zip(factors, params_list)):
        display_params = {}
        for p in ff.params:
            val = row.get(p.alias)
            display_params[p.alias] = param_value_display(p, val)
        rows.append({
            'index': idx,
            'factor_alias': factor.alias,
            'params': display_params,
        })
    return rows

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
    include_visible = request.args.get('include_visible') == '1'
    accounts = _visible_accounts_for(u, include_self=True) if include_visible else [{'username': u, 'alias': u}]
    current_acct = next((a for a in accounts if a.get('username') == u), None) or {}
    can_filter_organization = bool(current_acct.get('role') == 'super_admin' or current_acct.get('is_admin'))
    result = []
    for acct in accounts:
        owner = acct.get('username')
        if not owner:
            continue
        with _get_user_file_lock(owner):
            templates = _load_user_tpls(owner, 'params', ff_alias)
        for t in templates:
            result.append({
                'id': t['id'],
                'name': t['name'],
                'owner_username': owner,
                'owner_alias': _account_display_name(acct),
                'owner_organization_id': acct.get('organization_id') or '',
                'owner_organization_name': acct.get('organization_name') or '',
                'editable': owner == u,
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
    owner_username = (request.args.get('owner_username') or u).strip()
    if not _can_view_user_scope(u, owner_username):
        return jsonify({'success': False, 'error': '无权查看该用户配置'}), 403
    with _get_user_file_lock(owner_username):
        templates = _load_user_tpls(owner_username, 'params', ff_alias)
    tpl = next((t for t in templates if t['id'] == tpl_id), None)
    if not tpl:
        return jsonify({'success': False, 'error': '模板不存在'}), 404
    tpl = dict(tpl)
    tpl['owner_username'] = owner_username
    tpl['editable'] = owner_username == u
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
        return jsonify({'success': True, 'factor_rows': _build_factor_rows(ff, new_pl)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── 全局模板 ──────────────────────────────────────────────────────────────────

# ── 全局模板 ──────────────────────────────────────────────────────────────────
# scope_key: 隔离键，当前用因子家族 alias 作为值，后续可扩展为其他维度

@templates_bp.route('/api/global_templates/<scope_key>', methods=['GET'])
@login_required
def list_global_templates(scope_key):
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'global', scope_key=scope_key)
    result = []
    for t in templates:
        snap = t.get('snapshot', {})
        # 生成设置摘要
        summary = _build_snapshot_summary(snap)
        result.append({
            'id': t['id'],
            'name': t['name'],
            'ff_alias': t.get('ff_alias', ''),
            'scope_key': scope_key,
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


@templates_bp.route('/api/global_templates/<scope_key>', methods=['POST'])
@login_required
def save_global_template(scope_key):
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
        templates = _load_user_tpls(u, 'global', scope_key=scope_key)
        new_id = _new_tpl_id()
        templates.append({
            'id': new_id,
            'name': name,
            'ff_alias': ff_alias,
            'snapshot': snapshot,
        })
        _save_user_tpls(u, 'global', templates, scope_key=scope_key)
    return jsonify({'success': True, 'id': new_id})


@templates_bp.route('/api/global_templates/<scope_key>/<tpl_id>', methods=['GET'])
@login_required
def get_global_template(scope_key, tpl_id):
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'global', scope_key=scope_key)
    tpl = next((t for t in templates if t['id'] == tpl_id), None)
    if not tpl:
        return jsonify({'success': False, 'error': '模板不存在'}), 404
    return jsonify({'success': True, 'template': tpl})


@templates_bp.route('/api/global_templates/<scope_key>/<tpl_id>', methods=['PUT'])
@login_required
def update_global_template(scope_key, tpl_id):
    data = request.get_json()
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'global', scope_key=scope_key)
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
        _save_user_tpls(u, 'global', templates, scope_key=scope_key)
    return jsonify({'success': True})


@templates_bp.route('/api/global_templates/<scope_key>/<tpl_id>', methods=['DELETE'])
@login_required
def delete_global_template(scope_key, tpl_id):
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'global', scope_key=scope_key)
        before = len(templates)
        templates = [t for t in templates if t['id'] != tpl_id]
        if len(templates) == before:
            return jsonify({'success': False, 'error': '模板不存在'}), 404
        _save_user_tpls(u, 'global', templates, scope_key=scope_key)
    return jsonify({'success': True})


# ── scope 下模板覆盖的因子列表（按因子家族分组） ─────────────────────────

@templates_bp.route('/api/global_templates/<scope_key>/factors', methods=['GET'])
@login_required
def list_scope_factors(scope_key):
    """列出 scope_key 下所有全局模板覆盖的因子，
    从模板的 ff_alias 映射到实际的公共/自定义因子详情，按 factor_family 分组。"""
    u = _require_user()
    with _get_user_file_lock(u):
        templates = _load_user_tpls(u, 'global', scope_key=scope_key)

    # 收集所有 ff_alias
    ff_aliases = set()
    for t in templates:
        ff_alias = t.get('ff_alias', '').strip()
        if ff_alias:
            ff_aliases.add(ff_alias)

    # 构建因子映射：分别从公共因子和自定义因子中查找
    from .modules.custom_factors import _list_public_factors, _list_custom_factors
    public_factors = {f['id']: f for f in _list_public_factors()}
    custom_factors = {f['id']: f for f in _list_custom_factors(u)}

    # 按 factor_family 分组
    groups: dict[str, list] = {}
    for alias in sorted(ff_aliases):
        factor_info = None
        source = None
        if alias in public_factors:
            factor_info = public_factors[alias]
            source = 'public'
        elif alias in custom_factors:
            factor_info = custom_factors[alias]
            source = 'custom'

        if factor_info:
            family = factor_info.get('factor_family', 'FactorFamily')
            entry = {
                'id': alias,
                'name': factor_info.get('name', alias),
                'chinese_name': factor_info.get('chinese_name', ''),
                'category': factor_info.get('category', ''),
                'source': source,
                'updated_at': factor_info.get('updated_at', ''),
                'params_count': len(factor_info.get('params', [])),
                'description': factor_info.get('description', '')[:120] + ('...' if len(factor_info.get('description', '')) > 120 else ''),
            }
        else:
            family = 'FactorFamily'
            entry = {
                'id': alias,
                'name': alias,
                'chinese_name': '',
                'category': '',
                'source': 'unknown',
                'updated_at': '',
                'params_count': 0,
                'description': '',
            }

        groups.setdefault(family, []).append(entry)

    # 转为有序列表
    grouped = [{'family': k, 'factors': v} for k, v in sorted(groups.items())]

    return jsonify({
        'success': True,
        'scope_key': scope_key,
        'groups': grouped,
        'total_factors': sum(len(g['factors']) for g in grouped),
    })
