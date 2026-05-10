"""Business helpers for factor-library user-scoped parameter configs."""

from __future__ import annotations

import time

from server.modules.custom_factors.catalog import list_custom_factors, list_public_factors
from server.modules.custom_factors.param_config_store import (
    list_param_config_aliases,
    load_param_config,
    save_param_config,
)
from server.modules.shared.param_config import build_param_factor_item, serialize_param_rows
from server.services.accounts import (
    account_display_name,
    get_account,
    visible_accounts_for,
)
from server.services.factor_registry import (
    factor_group_key,
    get_custom_factor_instance,
    get_factor_family_instance,
)


def template_time_from_id(template: dict) -> str:
    if template.get('updated_at'):
        return template.get('updated_at')
    try:
        timestamp = int(str(template.get('id', ''))[:13]) / 1000
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))
    except Exception:
        return ''


def alias_map(factors: list[dict]) -> dict:
    result = {}
    for factor in factors:
        result[factor.get('id')] = factor
        result[factor.get('name')] = factor
    return result


def resolve_param_factor_family(owner_username: str, ff_alias: str, public_by_alias: dict, custom_by_alias: dict):
    custom_meta = custom_by_alias.get(ff_alias)
    if custom_meta:
        factor_family = get_custom_factor_instance(owner_username, custom_meta.get('id') or ff_alias)
        if factor_family is not None:
            return factor_family, dict(custom_meta, source='custom')
    public_meta = public_by_alias.get(ff_alias)
    if public_meta:
        return get_factor_family_instance(public_meta.get('id') or ff_alias), dict(public_meta, source='public')
    factor_family = get_factor_family_instance(ff_alias, username=owner_username)
    return factor_family, {
        'id': ff_alias,
        'name': getattr(factor_family, 'alias', ff_alias),
        'category': getattr(factor_family, 'category', '') or '',
        'chinese_name': getattr(factor_family, 'desc', '') or '',
        'description': getattr(factor_family, 'description', '') or '',
        'factor_family': factor_family.__class__.__name__,
        'source': 'unknown',
    }


def build_library_param_factor_item(
    current_username: str,
    owner_account: dict,
    ff_alias: str,
    config: dict,
    row: dict,
    row_index: int,
    public_by_alias: dict,
    custom_by_alias: dict,
) -> dict:
    owner_username = owner_account.get('username') or ''
    factor_family, meta = resolve_param_factor_family(owner_username, ff_alias, public_by_alias, custom_by_alias)
    account = dict(owner_account)
    account['alias'] = account_display_name(owner_account)
    return build_param_factor_item(factor_family, row or {}, row_index, account, current_username, meta=meta, config=config)


def build_factor_library_config_factors(current_username: str, owner_account: dict, ff_alias: str, config: dict) -> list:
    owner_username = owner_account.get('username') or ''
    public_by_alias = alias_map(list_public_factors())
    custom_by_alias = alias_map(list_custom_factors(owner_username))
    factors = []
    params_list = config.get('params_list') or []
    if not isinstance(params_list, list):
        return factors
    for row_index, row in enumerate(params_list):
        try:
            factors.append(build_library_param_factor_item(
                current_username,
                owner_account,
                ff_alias,
                config,
                row if isinstance(row, dict) else {},
                row_index,
                public_by_alias,
                custom_by_alias,
            ))
        except Exception:
            continue
    return factors


def build_param_factor_overview(current_username: str, include_subordinates: bool) -> dict:
    accounts = (
        visible_accounts_for(current_username, include_self=True)
        if include_subordinates
        else [get_account(current_username) or {'username': current_username}]
    )
    current_account = get_account(current_username) or {}
    can_filter_organization = bool(current_account.get('role') == 'super_admin' or current_account.get('is_admin'))
    public_by_alias = alias_map(list_public_factors())

    items = []
    errors = []
    for account in accounts:
        owner_username = account.get('username')
        if not owner_username:
            continue
        custom_by_alias = alias_map(list_custom_factors(owner_username))
        for ff_alias in list_param_config_aliases(owner_username):
            config = load_param_config(owner_username, ff_alias)
            if not config:
                continue
            params_list = config.get('params_list') or []
            for row_index, row in enumerate(params_list):
                try:
                    items.append(build_library_param_factor_item(
                        current_username,
                        account,
                        ff_alias,
                        config,
                        row if isinstance(row, dict) else {},
                        row_index,
                        public_by_alias,
                        custom_by_alias,
                    ))
                except Exception as exc:
                    errors.append({
                        'owner_username': owner_username,
                        'factor_family_alias': ff_alias,
                        'template_name': config.get('name') or '',
                        'row_index': row_index,
                        'error': str(exc),
                    })

    items.sort(key=lambda factor: (
        factor_group_key(str(factor.get('factor_family_alias') or factor.get('factor_family_name') or '')),
        factor.get('owner_organization_name') or factor.get('owner_organization_id') or '',
        factor.get('owner_alias') or factor.get('owner_username') or '',
        factor.get('factor_family_alias') or '',
        factor.get('factor_alias') or '',
        factor.get('template_name') or '',
    ))
    return {
        'factors': items,
        'errors': errors,
        'include_subordinates': include_subordinates,
        'current_username': current_username,
        'can_filter_organization': can_filter_organization,
    }


def list_param_config_users(current_username: str, ff_alias: str) -> dict:
    accounts = visible_accounts_for(current_username, include_self=True)
    current_account = get_account(current_username) or {}
    can_filter_organization = bool(current_account.get('role') == 'super_admin' or current_account.get('is_admin'))
    public_by_alias = alias_map(list_public_factors())

    users = []
    for account in accounts:
        owner_username = account.get('username')
        if not owner_username:
            continue
        config = load_param_config(owner_username, ff_alias)
        factors = []
        custom_by_alias = alias_map(list_custom_factors(owner_username))
        if config:
            params_list = config.get('params_list') or []
            if not isinstance(params_list, list):
                params_list = []
            for row_index, row in enumerate(params_list):
                try:
                    factors.append(build_library_param_factor_item(
                        current_username,
                        account,
                        ff_alias,
                        config,
                        row if isinstance(row, dict) else {},
                        row_index,
                        public_by_alias,
                        custom_by_alias,
                    ))
                except Exception:
                    continue
        users.append({
            'owner_username': owner_username,
            'owner_alias': account_display_name(account),
            'owner_organization_id': account.get('organization_id') or '',
            'owner_organization_name': account.get('organization_name') or '',
            'editable': owner_username == current_username,
            'config': {
                'id': config.get('id') if config else owner_username,
                'name': config.get('name') if config else owner_username,
                'updated_at': template_time_from_id(config) if config else '',
                'factor_count': len(config.get('params_list') or []) if config else 0,
                'params_list': config.get('params_list') if config else [],
            } if config else None,
            'factors': factors,
        })
    return {
        'users': users,
        'can_filter_organization': can_filter_organization,
    }


def save_current_user_param_config(current_username: str, ff_alias: str, params_list: list) -> tuple[dict, list]:
    factor_family = get_factor_family_instance(ff_alias, username=current_username)
    serialized_rows = serialize_param_rows(factor_family, params_list)
    config = save_param_config(current_username, ff_alias, serialized_rows)
    account = get_account(current_username) or {'username': current_username}
    factors = build_factor_library_config_factors(current_username, account, ff_alias, config)
    return config, factors
