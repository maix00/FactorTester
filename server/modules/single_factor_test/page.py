"""Single-factor-test page shell and content APIs."""

from __future__ import annotations

import os
import traceback

from flask import jsonify, render_template, request

from tools.data.account_manage import (
    account_display_name,
    can_view_user_scope,
    get_account,
)
from server.services.factor_registry import (
    factor_group_key,
    get_chinese_names,
    get_factor_family_instance,
    get_factor_groups,
)
from server.services.runtime_state import current_user, get_session_params
from server.modules.single_factor_test.view_helpers import (
    get_default_test_time_strings,
    get_factor_main_section_html,
)
from . import sft_bp


def _search_custom_factors(factors, query):
    """在自定义因子列表中搜索。"""
    q = query.lower()
    return [
        f for f in factors
        if q in f.get('name', '').lower()
        or q in f.get('chinese_name', '').lower()
        or q in f.get('category', '').lower()
    ]


def _get_sidebar_custom_factors(username: str, include_subordinates: bool) -> list:
    from server.modules.custom_factors.catalog import list_custom_factors, list_visible_custom_factors

    if include_subordinates:
        return list_visible_custom_factors(username)
    custom = list_custom_factors(username)
    acct = get_account(username) or {}
    for factor in custom:
        factor['owner_username'] = username
        factor['owner_alias'] = account_display_name(acct) or '我'
        factor['owner_organization_id'] = acct.get('organization_id') or ''
        factor['owner_organization_name'] = acct.get('organization_name') or ''
        factor['can_edit'] = True
    return custom


def _build_single_factor_sidebar_payload(search_query: str = '', include_subordinates: bool = False) -> dict:
    """Build the single-factor-test sidebar payload in the same shape as factor management."""
    factors_dir = os.path.join(os.getcwd(), 'Factors')
    _, factor_names = get_factor_groups(factors_dir)
    chinese_names = get_chinese_names(factors_dir)
    username = current_user()
    custom_factors = _get_sidebar_custom_factors(username, include_subordinates) if username else []

    if search_query:
        q = search_query.lower()
        factor_names = [n for n in factor_names if q in n.lower() or q in chinese_names.get(n, '').lower()]
        custom_factors = _search_custom_factors(custom_factors, q)

    public_factors = [
        {
            'id': name,
            'name': name,
            'type': 'public',
            'chinese_name': chinese_names.get(name, ''),
            'category': '公共',
            'owner_username': '',
            'owner_alias': '',
            'owner_organization_id': '',
            'owner_organization_name': '',
            'can_edit': False,
            'group': factor_group_key(name),
        }
        for name in sorted(factor_names)
    ]
    custom_payload = []
    for cf in custom_factors:
        name = cf.get('name') or cf.get('id') or ''
        custom_payload.append({
            'id': cf.get('id', ''),
            'name': name,
            'type': 'custom',
            'chinese_name': cf.get('chinese_name', '') or name,
            'category': cf.get('category', '') or '自编',
            'owner_username': cf.get('owner_username', ''),
            'owner_alias': cf.get('owner_alias', ''),
            'owner_organization_id': cf.get('owner_organization_id', ''),
            'owner_organization_name': cf.get('owner_organization_name', ''),
            'can_edit': bool(cf.get('can_edit')),
            'updated_at': cf.get('updated_at', ''),
            'group': factor_group_key(name),
        })
    return {
        'public_factors': public_factors,
        'custom_factors': custom_payload,
    }


def _render_single_factor_content(selected_name: str, factor_type: str = '', owner_username: str = '') -> str:
    username = current_user()
    factor_type = factor_type or 'public'
    if not selected_name:
        return '<div class="editor-placeholder">← 从左侧选择因子家族开始测试</div>'

    if factor_type == 'custom':
        if not username:
            return '<div class="section"><div class="section-title">错误</div><div style="color:#d40000;padding:20px;">请先登录</div></div>'
        owner_username = (owner_username or username or '').strip()
        if not can_view_user_scope(username, owner_username):
            return '<div class="section"><div class="section-title">错误</div><div style="color:#d40000;padding:20px;">无权查看该用户因子</div></div>'
        try:
            ff = get_factor_family_instance(selected_name, username=owner_username)
            if ff is None:
                return f'''<div class="section"><div class="section-title">错误</div><div style="color:#d40000;padding:20px;">无法加载自定义因子 "{selected_name}"</div></div>'''
            math_expr = getattr(ff, 'math_expr', '')
            cf_data = getattr(ff, '_custom_factor_data', {})
            display_alias = cf_data.get('name', '') or getattr(ff, 'alias', '') or selected_name
            desc = cf_data.get('chinese_name', '') or getattr(ff, 'desc', '')
            description = cf_data.get('description', '') or getattr(ff, 'description', '') or ''
            params = ff.params
            from server.modules.shared.param_meta import serialize_param_meta

            param_metas = [serialize_param_meta(p) for p in params]
            param_aliases = [p.alias for p in params]
            session_params = get_session_params(display_alias, ff)
            factors = ff.get_factors(params_list=session_params)
            start_date, end_date, start_time, end_time = get_default_test_time_strings()
            return render_template(
                'factor_main.html',
                factor_family_alias=display_alias,
                chinese_name=desc,
                math_expr=math_expr,
                description=description,
                params=params,
                param_metas=param_metas,
                param_aliases=param_aliases,
                factors=factors,
                start_date=start_date,
                end_date=end_date,
                start_time=start_time,
                end_time=end_time,
                is_custom=True,
                factor_type='custom',
            )
        except Exception as e:
            traceback.print_exc()
            return f'''<div class="section"><div class="section-title">错误</div><div style="color:#d40000;padding:20px;">加载自定义因子 "{selected_name}" 失败:<br><pre>{str(e)}</pre></div></div>'''

    factors_dir = os.path.join(os.getcwd(), 'Factors')
    _, factor_names = get_factor_groups(factors_dir)
    if selected_name not in factor_names:
        return f'<div class="editor-placeholder">因子 "{selected_name}" 未找到</div>'
    try:
        return get_factor_main_section_html(selected_name)
    except Exception as e:
        traceback.print_exc()
        return f'''
            <div class="section">
                <div class="section-title">错误</div>
                <div style="color:#d40000;padding:20px;">
                    加载因子 "{selected_name}" 失败:<br>
                    <pre>{str(e)}</pre>
                </div>
            </div>
        '''


@sft_bp.route('/single_factor_test', methods=['GET'])
def single_factor_page():
    search_query = request.args.get('search', '')
    selected_name = request.args.get('factor', '')
    factor_type = request.args.get('type', '')
    include_subordinates = request.args.get('include_subordinates') == '1'
    owner_username = request.args.get('owner_username', '')
    return render_template(
        'single_factor_test.html',
        search_query=search_query,
        include_subordinates=include_subordinates,
        initial_factor=selected_name,
        initial_factor_type=factor_type or 'public',
        initial_owner_username=owner_username,
    )


@sft_bp.route('/single_factor_test/api/list', methods=['GET'])
def single_factor_list_api():
    search_query = request.args.get('search', '')
    include_subordinates = request.args.get('include_subordinates') == '1'
    payload = _build_single_factor_sidebar_payload(search_query, include_subordinates)
    return jsonify({'success': True, **payload})


@sft_bp.route('/single_factor_test/api/content', methods=['GET'])
def single_factor_content_api():
    selected_name = request.args.get('factor', '')
    factor_type = request.args.get('type', '') or 'public'
    owner_username = request.args.get('owner_username', '')
    html = _render_single_factor_content(selected_name, factor_type, owner_username)
    return jsonify({'success': True, 'html': html})
