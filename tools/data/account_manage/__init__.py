from __future__ import annotations

import hashlib
import hmac
import re
import threading

from .user import User
from tools.data.sqlite.account_manager import (
    DEFAULT_SCOPE_KEY,
    delete_factor_param_config as _delete_factor_param_config,
    delete_scope as _delete_scope,
    ensure_account_manager_sqlite_store,
    factor_research_config_hash as _factor_research_config_hash,
    delete_factor_research_run as _delete_factor_research_run,
    list_factor_research_runs as _list_factor_research_runs,
    ensure_scope_exists as _ensure_scope_exists,
    list_all_factor_param_aliases_across_scopes as _list_all_aliases_across_scopes,
    list_factor_param_config_aliases as _list_factor_param_config_aliases,
    list_factor_param_config_scopes as _list_factor_param_config_scopes,
    load_accounts as _load_accounts,
    load_levels as _load_levels,
    load_organizations as _load_organizations,
    load_factor_param_config as _load_factor_param_config,
    load_product_groups as _load_product_groups,
    list_factor_sets as _list_factor_sets,
    get_factor_set as _get_factor_set,
    normalize_product_group as _normalize_product_group,
    rename_scope as _rename_scope,
    save_accounts as _save_accounts,
    save_factor_research_run as _save_factor_research_run,
    save_levels as _save_levels,
    save_organizations as _save_organizations,
    save_factor_param_config as _save_factor_param_config,
    save_product_groups as _save_product_groups,
    save_factor_set as _save_factor_set,
    delete_factor_set as _delete_factor_set,
)

accounts_lock = threading.Lock()
organizations_lock = threading.Lock()
levels_lock = threading.Lock()

DEFAULT_ORGANIZATION_ID = 'default'
DEFAULT_ORGANIZATION_NAME = '默认机构'
ROLE_SUPER_ADMIN = 'super_admin'
ROLE_ORG_ADMIN = 'org_admin'
ROLE_LEVEL_ADMIN = 'level_admin'
ROLE_DEVELOPER = 'developer'
ROLE_USER = 'user'
ADMIN_ROLES = {ROLE_SUPER_ADMIN, ROLE_ORG_ADMIN, ROLE_LEVEL_ADMIN}


def account_display_name(account: dict | None) -> str:
    if not account:
        return ""
    return str(account.get('alias') or account.get('username') or '')


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 200_000).hex()


def verify_password(password: str, salt: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_password(password, salt), stored_hash)


def load_accounts() -> list:
    ensure_account_manager_sqlite_store()
    return _load_accounts()


def save_accounts(accounts: list) -> None:
    _save_accounts(accounts)


def load_organizations() -> list:
    ensure_account_manager_sqlite_store()
    return _load_organizations()


def save_organizations(organizations: list) -> None:
    _save_organizations(organizations)


def load_levels() -> list:
    ensure_account_manager_sqlite_store()
    return _load_levels()


def save_levels(levels: list) -> None:
    _save_levels(levels)


def slugify_org_id(name: str) -> str:
    raw = re.sub(r'\s+', '_', (name or '').strip())
    raw = re.sub(r'[^\w\u4e00-\u9fff-]', '', raw)
    return raw or DEFAULT_ORGANIZATION_ID


def compose_account_username(organization_id: str, alias: str, serial: int) -> str:
    org_id = (organization_id or DEFAULT_ORGANIZATION_ID).strip() or DEFAULT_ORGANIZATION_ID
    return f'{org_id}${alias}@{serial}'


def next_account_username(accounts: list, organization_id: str, alias: str) -> str:
    org_id = (organization_id or DEFAULT_ORGANIZATION_ID).strip() or DEFAULT_ORGANIZATION_ID
    same_name = [
        account for account in accounts
        if (account.get('alias') or account.get('username')) == alias
        and (account.get('organization_id') or DEFAULT_ORGANIZATION_ID) == org_id
    ]
    serial = max(
        (
            int(account['username'].rsplit('@', 1)[1])
            for account in same_name
            if '@' in account.get('username', '') and account['username'].rsplit('@', 1)[1].isdigit()
        ),
        default=0,
    ) + 1
    return compose_account_username(org_id, alias, serial)


def normalize_organization(org: dict) -> dict:
    normalized = dict(org or {})
    name = (normalized.get('name') or normalized.get('organization_name') or DEFAULT_ORGANIZATION_NAME).strip()
    normalized['name'] = name
    normalized['id'] = (normalized.get('id') or normalized.get('organization_id') or slugify_org_id(name)).strip()
    normalized.setdefault('description', '')
    return normalized


def normalize_level(level: dict) -> dict:
    normalized = dict(level or {})
    org_id = (normalized.get('organization_id') or DEFAULT_ORGANIZATION_ID).strip() or DEFAULT_ORGANIZATION_ID
    normalized['organization_id'] = org_id
    normalized['id'] = (normalized.get('id') or '').strip()
    normalized['name'] = (normalized.get('name') or '').strip()
    normalized['parent_level_id'] = (normalized.get('parent_level_id') or '').strip()
    normalized['manager_username'] = (normalized.get('manager_username') or '').strip()
    return normalized


def normalize_levels(levels: list) -> list:
    return [normalize_level(level) for level in levels]


def root_level_id_for_org(organization_id: str) -> str:
    return f'{organization_id}__ROOT'


def ensure_root_levels(levels: list, organizations: list) -> list:
    result = normalize_levels(levels)
    existed = {level.get('id') for level in result}
    for org in organizations:
        org_id = (org.get('id') or DEFAULT_ORGANIZATION_ID).strip() or DEFAULT_ORGANIZATION_ID
        rid = root_level_id_for_org(org_id)
        if rid in existed:
            continue
        result.append({
            'id': rid,
            'organization_id': org_id,
            'name': '默认层级',
            'parent_level_id': '',
            'manager_username': '',
        })
        existed.add(rid)
    return result


def list_levels_with_roots() -> list:
    organizations = list_organizations_with_default()
    with levels_lock:
        levels = normalize_levels(load_levels())
    return ensure_root_levels(levels, organizations)


def list_organizations_with_default() -> list:
    with organizations_lock:
        organizations = [normalize_organization(org) for org in load_organizations()]
    if not any(org.get('id') == DEFAULT_ORGANIZATION_ID for org in organizations):
        organizations.insert(0, {
            'id': DEFAULT_ORGANIZATION_ID,
            'name': DEFAULT_ORGANIZATION_NAME,
            'description': '系统默认机构',
        })
    return organizations


def normalize_account(account: dict) -> dict:
    normalized = dict(account or {})
    normalized.setdefault('organization_id', DEFAULT_ORGANIZATION_ID)
    normalized.setdefault('organization_name', DEFAULT_ORGANIZATION_NAME)
    normalized.setdefault('parent_username', '')
    normalized.setdefault('level_id', '')
    if normalized.get('is_admin') and not normalized.get('role'):
        normalized.setdefault('role', ROLE_SUPER_ADMIN)
    else:
        normalized.setdefault('role', ROLE_USER)
    normalized['is_admin'] = bool(normalized.get('is_admin') or normalized.get('role') == ROLE_SUPER_ADMIN)
    normalized['is_developer'] = bool(normalized.get('is_developer') or normalized.get('role') == ROLE_DEVELOPER)
    return normalized


def normalize_accounts(accounts: list) -> list:
    return [normalize_account(account) for account in accounts]


def get_account(username: str | None) -> dict | None:
    if not username:
        return None
    with accounts_lock:
        accounts = normalize_accounts(load_accounts())
    return next((account for account in accounts if account.get('username') == username), None)


def _descendant_level_ids(levels: list, root_level_id: str) -> set[str]:
    children = {}
    for level in levels:
        parent = level.get('parent_level_id') or ''
        children.setdefault(parent, []).append(level.get('id') or '')
    result = set()
    stack = [root_level_id]
    while stack:
        node = stack.pop()
        if not node or node in result:
            continue
        result.add(node)
        stack.extend(children.get(node, []))
    return result


def is_super_admin_account(account: dict | None) -> bool:
    return bool(account and (account.get('role') == ROLE_SUPER_ADMIN or account.get('is_admin')))


def is_org_admin_account(account: dict | None) -> bool:
    return bool(account and (account.get('role') == ROLE_ORG_ADMIN or is_super_admin_account(account)))


def is_level_admin_account(account: dict | None) -> bool:
    return bool(account and (account.get('role') == ROLE_LEVEL_ADMIN or is_org_admin_account(account)))


def is_any_admin_account(account: dict | None) -> bool:
    return bool(account and (account.get('role') in ADMIN_ROLES or is_super_admin_account(account)))


def is_developer_account(account: dict | None) -> bool:
    normalized = normalize_account(account or {})
    return bool(normalized.get('is_developer'))


def visible_accounts_for(username: str | None, include_self: bool = True) -> list:
    if not username:
        return []
    with accounts_lock:
        accounts = normalize_accounts(load_accounts())
    current = next((account for account in accounts if account.get('username') == username), None)
    if current is None:
        return []
    levels = list_levels_with_roots()
    org_id = current.get('organization_id') or DEFAULT_ORGANIZATION_ID
    current_level_id = current.get('level_id') or root_level_id_for_org(org_id)
    if is_super_admin_account(current):
        visible = accounts
    elif current.get('role') == ROLE_ORG_ADMIN:
        visible = [
            account for account in accounts
            if (account.get('organization_id') or DEFAULT_ORGANIZATION_ID) == org_id
        ]
    elif current.get('role') == ROLE_LEVEL_ADMIN:
        scope_levels = _descendant_level_ids(levels, current_level_id)
        visible = [
            account for account in accounts
            if (account.get('organization_id') or DEFAULT_ORGANIZATION_ID) == org_id
            and ((account.get('level_id') or root_level_id_for_org(org_id)) in scope_levels)
        ]
    else:
        visible = [
            account for account in accounts
            if (account.get('organization_id') or DEFAULT_ORGANIZATION_ID) == org_id
            and ((account.get('level_id') or root_level_id_for_org(org_id)) == current_level_id)
        ]
        if include_self:
            visible.insert(0, current)
    if include_self and current not in visible:
        visible.insert(0, current)
    if not include_self:
        visible = [account for account in visible if account.get('username') != username]
    return visible


def visible_usernames_for(username: str | None, include_self: bool = True) -> list[str]:
    return [
        account.get('username')
        for account in visible_accounts_for(username, include_self=include_self)
        if account.get('username')
    ]


def can_view_user_scope(current_username: str | None, target_username: str | None) -> bool:
    if not current_username or not target_username:
        return False
    return target_username in set(visible_usernames_for(current_username, include_self=True))


def direct_child_accounts_for(username: str | None) -> list:
    if not username:
        return []
    with accounts_lock:
        accounts = normalize_accounts(load_accounts())
    return [account for account in accounts if account.get('parent_username') == username]


def can_manage_user_account(current_username: str | None, target_username: str | None) -> bool:
    if not current_username or not target_username or current_username == target_username:
        return False
    with accounts_lock:
        accounts = normalize_accounts(load_accounts())
    current = next((account for account in accounts if account.get('username') == current_username), None)
    target = next((account for account in accounts if account.get('username') == target_username), None)
    if not current or not target:
        return False
    levels = list_levels_with_roots()
    current_org = current.get('organization_id') or DEFAULT_ORGANIZATION_ID
    target_org = target.get('organization_id') or DEFAULT_ORGANIZATION_ID
    current_level = current.get('level_id') or root_level_id_for_org(current_org)
    target_level = target.get('level_id') or root_level_id_for_org(target_org)
    if is_super_admin_account(current):
        return True
    if is_super_admin_account(target):
        return False
    if current.get('role') == ROLE_ORG_ADMIN:
        return current_org == target_org
    if current.get('role') == ROLE_LEVEL_ADMIN:
        if current_org != target_org:
            return False
        scope_levels = _descendant_level_ids(levels, current_level)
        return target_level in scope_levels
    return False


def serialize_account_public(account: dict | None, current_username: str | None = None) -> dict:
    normalized = normalize_account(account or {})
    return {
        'username': normalized.get('username', ''),
        'alias': normalized.get('alias') or normalized.get('username', ''),
        'role': normalized.get('role') or ROLE_USER,
        'is_admin': bool(normalized.get('is_admin')),
        'is_developer': bool(normalized.get('is_developer')),
        'organization_id': normalized.get('organization_id') or DEFAULT_ORGANIZATION_ID,
        'organization_name': normalized.get('organization_name') or DEFAULT_ORGANIZATION_NAME,
        'level_id': normalized.get('level_id') or '',
        'parent_username': normalized.get('parent_username') or '',
        'can_manage': can_manage_user_account(current_username, normalized.get('username')) if current_username else False,
    }


def visible_organizations_for(username: str | None) -> list:
    account = get_account(username)
    organizations = list_organizations_with_default()
    if not account:
        return []
    if is_super_admin_account(account):
        return organizations
    org_id = account.get('organization_id') or DEFAULT_ORGANIZATION_ID
    return [org for org in organizations if org.get('id') == org_id]


def can_manage_organization(current_username: str | None, organization_id: str | None) -> bool:
    account = get_account(current_username)
    if not account:
        return False
    if is_super_admin_account(account):
        return True
    if account.get('role') == ROLE_ORG_ADMIN:
        return (account.get('organization_id') or DEFAULT_ORGANIZATION_ID) == (
            organization_id or DEFAULT_ORGANIZATION_ID
        )
    return False


def can_manage_level(current_username: str | None, level_id: str | None) -> bool:
    account = get_account(current_username)
    if not account:
        return False
    if is_super_admin_account(account):
        return True
    levels = list_levels_with_roots()
    target = next((level for level in levels if level.get('id') == (level_id or '')), None)
    if target is None:
        return False
    account_org = account.get('organization_id') or DEFAULT_ORGANIZATION_ID
    target_org = target.get('organization_id') or DEFAULT_ORGANIZATION_ID
    if account.get('role') == ROLE_ORG_ADMIN:
        return account_org == target_org
    if account.get('role') == ROLE_LEVEL_ADMIN:
        account_level = account.get('level_id') or root_level_id_for_org(account_org)
        scope_levels = _descendant_level_ids(levels, account_level)
        return account_org == target_org and (target.get('id') or '') in scope_levels
    return False


def load_product_groups(username: str) -> list:
    ensure_account_manager_sqlite_store()
    return _load_product_groups(username)


def save_product_groups(username: str, groups: list) -> None:
    ensure_account_manager_sqlite_store()
    _save_product_groups(username, groups)


def list_factor_sets(username: str) -> list[dict]:
    ensure_account_manager_sqlite_store()
    return _list_factor_sets(username)


def get_factor_set(username: str, target_ref: str) -> dict | None:
    ensure_account_manager_sqlite_store()
    return _get_factor_set(username, target_ref)


def save_factor_set(username: str, value: dict) -> dict:
    ensure_account_manager_sqlite_store()
    return _save_factor_set(username, value)


def delete_factor_set(username: str, target_ref: str) -> bool:
    ensure_account_manager_sqlite_store()
    return _delete_factor_set(username, target_ref)


def normalize_product_group(product_group: str | None) -> str:
    return _normalize_product_group(product_group)


def load_factor_param_config(username: str, ff_alias: str, scope_key: str = DEFAULT_SCOPE_KEY) -> dict | None:
    ensure_account_manager_sqlite_store()
    return _load_factor_param_config(username, ff_alias, scope_key)


def save_factor_param_config(
    username: str,
    ff_alias: str,
    params_list: list,
    scope_key: str = DEFAULT_SCOPE_KEY,
    *,
    metadata: dict | None = None,
) -> dict:
    ensure_account_manager_sqlite_store()
    return _save_factor_param_config(username, ff_alias, params_list, scope_key, metadata=metadata)


def delete_factor_param_config(username: str, ff_alias: str, scope_key: str = DEFAULT_SCOPE_KEY) -> bool:
    ensure_account_manager_sqlite_store()
    return _delete_factor_param_config(username, ff_alias, scope_key)


def list_factor_param_config_aliases(username: str, scope_key: str = DEFAULT_SCOPE_KEY) -> list[str]:
    ensure_account_manager_sqlite_store()
    return _list_factor_param_config_aliases(username, scope_key)


def list_factor_param_config_scopes(username: str) -> list[str]:
    ensure_account_manager_sqlite_store()
    return _list_factor_param_config_scopes(username)


def list_all_factor_param_aliases_across_scopes(username: str) -> dict[str, list[str]]:
    ensure_account_manager_sqlite_store()
    return _list_all_aliases_across_scopes(username)


def ensure_scope_exists(username: str, scope_key: str = DEFAULT_SCOPE_KEY) -> str:
    ensure_account_manager_sqlite_store()
    return _ensure_scope_exists(username, scope_key)


def rename_scope(username: str, old_scope_key: str, new_scope_key: str) -> bool:
    ensure_account_manager_sqlite_store()
    return _rename_scope(username, old_scope_key, new_scope_key)


def delete_scope(username: str, scope_key: str) -> bool:
    ensure_account_manager_sqlite_store()
    return _delete_scope(username, scope_key)


def factor_research_config_hash(config: dict | None) -> str:
    return _factor_research_config_hash(config)


def save_factor_research_run(
    username: str,
    *,
    ff_alias: str,
    factor_alias: str,
    start_date: str,
    end_date: str,
    test_type: str,
    metrics: dict,
    product_group: str = "",
    factor_source: str = "",
    config: dict | None = None,
    config_hash_value: str | None = None,
    report_path: str = "",
    artifact_path: str = "",
    note: str = "",
    sample_role: str = "",
    regime_label: str = "",
    slice_name: str = "",
    run_id: str | None = None,
) -> dict:
    ensure_account_manager_sqlite_store()
    return _save_factor_research_run(
        username,
        ff_alias=ff_alias,
        factor_alias=factor_alias,
        start_date=start_date,
        end_date=end_date,
        test_type=test_type,
        metrics=metrics,
        product_group=product_group,
        factor_source=factor_source,
        config=config,
        config_hash_value=config_hash_value,
        report_path=report_path,
        artifact_path=artifact_path,
        note=note,
        sample_role=sample_role,
        regime_label=regime_label,
        slice_name=slice_name,
        run_id=run_id,
    )


def list_factor_research_runs(
    username: str,
    *,
    ff_alias: str | None = None,
    factor_alias: str | None = None,
    product_group: str | None = None,
    test_type: str | None = None,
    sample_role: str | None = None,
    regime_label: str | None = None,
    slice_name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    overlap: bool = True,
    min_metrics: dict[str, float] | None = None,
    max_metrics: dict[str, float] | None = None,
    order_by_metric: str | None = None,
    descending: bool = True,
    limit: int | None = None,
) -> list[dict]:
    ensure_account_manager_sqlite_store()
    return _list_factor_research_runs(
        username,
        ff_alias=ff_alias,
        factor_alias=factor_alias,
        product_group=product_group,
        test_type=test_type,
        sample_role=sample_role,
        regime_label=regime_label,
        slice_name=slice_name,
        start_date=start_date,
        end_date=end_date,
        overlap=overlap,
        min_metrics=min_metrics,
        max_metrics=max_metrics,
        order_by_metric=order_by_metric,
        descending=descending,
        limit=limit,
    )


def delete_factor_research_run(username: str, run_id: str) -> bool:
    ensure_account_manager_sqlite_store()
    return _delete_factor_research_run(username, run_id)
