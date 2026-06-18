"""HTML helpers for the single-factor-test page."""

from __future__ import annotations

import html

import pandas as pd
from flask import render_template

import settings as Settings
from server.modules.shared.param_meta import serialize_param_meta
from server.services.factor_registry import factor_group_key, get_factor_family_instance
from server.services.runtime_state import get_session_params


def get_default_test_time_strings():
    start_date = getattr(Settings, 'default_test_start_date', '2025-01-02')
    end_date = getattr(Settings, 'default_test_end_date', '2025-05-31')
    start_date = start_date.strftime('%Y-%m-%d') if isinstance(start_date, pd.Timestamp) else str(start_date)
    end_date = end_date.strftime('%Y-%m-%d') if isinstance(end_date, pd.Timestamp) else str(end_date)
    start_time = getattr(Settings, 'default_day_start_time', '09:30')
    end_time = getattr(Settings, 'default_day_end_time', '15:00')
    return start_date, end_date, start_time, end_time


def build_group_html(
    groups,
    chinese_names: dict | None = None,
    custom_factors: list | None = None,
    selected_name: str | None = None,
    selected_type: str | None = None,
    selected_owner_username: str | None = None,
):
    """构建侧边栏因子列表 HTML。"""
    if not groups and not custom_factors:
        return '<div style="color:#888;">无匹配因子</div>'
    chinese_names = chinese_names or {}
    custom_factors = custom_factors or []

    merged_groups = {}
    for group, names in groups.items():
        for name in sorted(names):
            chinese_name = chinese_names.get(name, '')
            merged_groups.setdefault(group, []).append({
                'name': name,
                'type': 'public',
                'id': name,
                'chinese_name': chinese_name,
                'owner_key': '公共',
                'owner_label': '公共',
            })

    for custom_factor in custom_factors:
        factor_name = custom_factor.get('name', '') or custom_factor.get('id', '')
        factor_group = factor_group_key(str(factor_name))
        merged_groups.setdefault(factor_group, []).append({
            'name': factor_name,
            'type': 'custom',
            'id': custom_factor.get('id', ''),
            'chinese_name': custom_factor.get('chinese_name', '') or factor_name,
            'category': custom_factor.get('category', ''),
            'owner_username': custom_factor.get('owner_username', ''),
            'owner_alias': custom_factor.get('owner_alias', ''),
            'owner_organization_id': custom_factor.get('owner_organization_id', ''),
            'owner_organization_name': custom_factor.get('owner_organization_name', ''),
            'can_edit': bool(custom_factor.get('can_edit')),
            'owner_key': (
                f"{custom_factor.get('owner_organization_name') or custom_factor.get('owner_organization_id') or '未分机构'}"
                f"/{custom_factor.get('owner_alias') or custom_factor.get('owner_username') or '未知用户'}"
            ),
            'owner_label': (
                '我的因子'
                if custom_factor.get('can_edit')
                else f"{custom_factor.get('owner_organization_name') or custom_factor.get('owner_organization_id') or '未分机构'} / {custom_factor.get('owner_alias') or custom_factor.get('owner_username') or '未知用户'}"
            ),
        })

    for group in merged_groups:
        merged_groups[group].sort(key=lambda item: (item.get('owner_key', ''), item['name']))

    group_html = ""
    for group in sorted(merged_groups.keys()):
        items = merged_groups[group]
        owners = {}
        for item in items:
            owners.setdefault(item.get('owner_key') or '公共', []).append(item)
        group_html += '<div class="factor-group collapsible-factor-node collapsible-factor-group">'
        group_html += (
            '<button class="collapsible-factor-header" type="button">'
            '<span class="caret">▶</span>'
            f'<span class="collapsible-factor-title">{html.escape(str(group))}</span>'
            f'<span class="collapsible-factor-count">{len(items)}</span>'
            '</button><div class="collapsible-factor-body">'
        )
        for owner_key in sorted(owners.keys()):
            owner_items = owners[owner_key]
            owner_label = owner_items[0].get('owner_label') or owner_key
            group_html += '<div class="collapsible-factor-node collapsible-factor-owner">'
            group_html += (
                '<button class="collapsible-factor-header" type="button">'
                '<span class="caret">▶</span>'
                f'<span class="collapsible-factor-title">{html.escape(str(owner_label))}</span>'
                f'<span class="collapsible-factor-count">{len(owner_items)}</span>'
                '</button><div class="collapsible-factor-body">'
            )
            group_html += '<ul class="factor-list">'
            for item in owner_items:
                is_custom = item['type'] == 'custom'
                if is_custom:
                    owner = item.get('owner_username') or ''
                    href = f'?factor={html.escape(str(item["id"]))}&amp;type=custom'
                    if owner:
                        href += f'&amp;owner_username={html.escape(str(owner))}'
                else:
                    href = f'?factor={html.escape(str(item["id"]))}'
                is_active = False
                if selected_name:
                    if is_custom:
                        is_active = (
                            selected_type == 'custom'
                            and (selected_owner_username or '') == (item.get('owner_username') or '')
                            and selected_name in {(item.get('id') or ''), (item.get('name') or '')}
                        )
                    else:
                        is_active = selected_type != 'custom' and selected_name == (item.get('id') or '')
                chinese_name = item.get('chinese_name', '')
                source_text = '我' if item.get('can_edit') else (item.get('owner_alias') or '下级')
                source_tag = f' <span class="factor-source-tag factor-source-custom">{html.escape(source_text)}</span>' if is_custom else ' <span class="factor-source-tag factor-source-public">公共</span>'
                cat_tag = ''
                if is_custom and item.get('category'):
                    cat_tag = f' <span style="color:#999;font-size:11px;">[{html.escape(str(item["category"]))}]</span>'
                name_html = html.escape(str(item["name"]))
                if chinese_name:
                    label = f'{name_html}{source_tag} <span class="factor-cn-name">{html.escape(str(chinese_name))}</span>{cat_tag}'
                else:
                    label = f'{name_html}{source_tag}{cat_tag}'
                active_cls = ' class="active"' if is_active else ''
                group_html += f'<li><a{active_cls} href="{href}">{label}</a></li>'
            group_html += '</ul></div></div>'
        group_html += '</div></div>'

    return group_html


def get_factor_main_section_html(factor_family_alias):
    try:
        factor_family = get_factor_family_instance(factor_family_alias)
        math_expr = getattr(factor_family, 'math_expr', '')
        chinese_name = getattr(factor_family, 'desc', '') or getattr(factor_family, 'chinese_name', '') or ''
        description = getattr(factor_family, 'description', '') or ''
        params = factor_family.params
        param_metas = [serialize_param_meta(param) for param in params]
        param_aliases = [param.alias for param in params]
        factors = factor_family.get_factors(params_list=get_session_params(factor_family_alias, factor_family))
        start_date, end_date, start_time, end_time = get_default_test_time_strings()
        return render_template(
            'factor_main.html',
            factor_family_alias=factor_family_alias,
            chinese_name=chinese_name,
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
        )
    except Exception as exc:
        return f"""
            <div class="section">
                <div class="section-title">当前因子: <b style="color:#0078d4;">{factor_family_alias}</b></div>
                <div style="color:#d40000;padding:20px;">加载因子失败: {exc}</div>
            </div>
        """
