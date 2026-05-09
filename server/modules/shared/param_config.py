"""Shared helpers for FactorFamily parameter rows.

Routes still own their storage semantics: single-factor tests store rows in the
session, while the factor library stores one user-scoped config per family.
"""

from __future__ import annotations


def normalize_param_rows(factor_family, params_list: list) -> list:
    normalized_rows = []
    for params in params_list:
        if not isinstance(params, dict):
            raise ValueError('参数行必须是对象')
        normalized = factor_family._normalize_param_kwargs(**params)
        factor_family._check_in_space(**normalized)
        normalized_rows.append({
            p.alias: p._value_space.rectify(normalized[p.alias]) if p.alias in normalized else p.default_value
            for p in factor_family.params
        })
    return normalized_rows


def normalize_param_row(factor_family, params: dict) -> dict:
    return normalize_param_rows(factor_family, [params])[0]


def param_value_display(param, value) -> str:
    if value is None:
        return ''
    try:
        return param._value_space.alias(value)
    except Exception:
        return str(value)


def serialize_param_rows(factor_family, params_list: list) -> list:
    """Normalize rows, then store JSON-safe value aliases."""
    normalized_rows = normalize_param_rows(factor_family, params_list)
    rows = []
    seen_aliases = set()
    for row in normalized_rows:
        factor_alias = factor_family.get_alias(**row)
        if factor_alias in seen_aliases:
            continue
        seen_aliases.add(factor_alias)
        rows.append({
            p.alias: param_value_display(p, row.get(p.alias))
            for p in factor_family.params
        })
    return rows


def build_param_factor_item(
    factor_family,
    params: dict,
    row_idx: int,
    owner_acct: dict,
    current_username: str,
    meta: dict | None = None,
    config: dict | None = None,
) -> dict:
    meta = meta or {}
    config = config or {}
    owner_username = owner_acct.get('username') or ''
    normalized_row = normalize_param_row(factor_family, params)
    params_display = [
        {
            'alias': p.alias,
            'value': param_value_display(p, normalized_row.get(p.alias)),
        }
        for p in factor_family.params
    ]
    source = meta.get('source') or 'unknown'
    return {
        'id': f"{owner_username}:{getattr(factor_family, 'alias', '')}:{config.get('id')}:{row_idx}",
        'factor_alias': factor_family.get_alias(**normalized_row),
        'factor_family_alias': getattr(factor_family, 'alias', None) or meta.get('name') or '',
        'factor_family_id': meta.get('id') or getattr(factor_family, 'alias', ''),
        'factor_family_name': meta.get('name') or getattr(factor_family, 'alias', ''),
        'chinese_name': meta.get('chinese_name') or '',
        'category': meta.get('category') or '',
        'source': source,
        'source_label': '公共因子' if source == 'public' else ('自定义因子' if source == 'custom' else '未知来源'),
        'template_id': config.get('id') or '',
        'template_name': config.get('name') or '未命名配置',
        'template_row_index': row_idx,
        'params': params_display,
        'params_count': len(params_display),
        'owner_username': owner_username,
        'owner_alias': owner_acct.get('alias') or owner_username,
        'owner_organization_id': owner_acct.get('organization_id') or '',
        'owner_organization_name': owner_acct.get('organization_name') or '',
        'can_edit': owner_username == current_username,
        'updated_at': config.get('updated_at') or '',
    }
