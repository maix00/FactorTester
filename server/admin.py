"""
Admin Blueprint: organization and user hierarchy management.
"""
from __future__ import annotations
import base64
import re
import secrets
from typing import Any, cast

from flask import Blueprint, current_app, request, jsonify
import orjson

from server.jobs.repository import JobRepository
from server.services.http_auth import login_required
from server.services.research_configurations import delete_owner_configurations
from server.services.session_runtime import require_user
from tools.data.account_manage import (
    accounts_lock, load_accounts, save_accounts,
    organizations_lock, load_organizations, save_organizations,
    normalize_accounts, normalize_organization, list_organizations_with_default,
    visible_accounts_for, visible_organizations_for,
    serialize_account_public, get_account,
    hash_password, verify_password,
    DEFAULT_ORGANIZATION_ID, DEFAULT_ORGANIZATION_NAME,
    ROLE_SUPER_ADMIN, ROLE_ORG_ADMIN, ROLE_LEVEL_ADMIN, ROLE_DEVELOPER, ROLE_USER,
    is_super_admin_account, is_org_admin_account, is_level_admin_account,
    can_manage_user_account, can_manage_organization,
    can_manage_level,
    next_account_username,
    levels_lock, load_levels, save_levels, normalize_levels,
    list_levels_with_roots, root_level_id_for_org,
)

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

ROLE_LABELS = {
    ROLE_SUPER_ADMIN: '超级管理员',
    ROLE_ORG_ADMIN: '机构管理员',
    ROLE_LEVEL_ADMIN: '层级管理员',
    ROLE_DEVELOPER: '开发人员',
    ROLE_USER: '普通用户',
}


def _require_admin_account() -> tuple[str, dict[str, Any] | None, Any]:
    username = require_user()
    acct = get_account(username)
    if not (is_super_admin_account(acct) or is_org_admin_account(acct) or is_level_admin_account(acct)):
        return username, acct, (jsonify({'success': False, 'error': '需要管理员权限'}), 403)
    return username, acct, None


def _job_repository() -> JobRepository:
    """Reuse schema-ready state across read-only admin queue requests."""
    repository = current_app.extensions.get('job_repository')
    if not isinstance(repository, JobRepository):
        repository = JobRepository()
        current_app.extensions['job_repository'] = repository
    return repository


def _validate_alias(alias: str) -> bool:
    return bool(re.match(r'^[A-Za-z0-9_\u4e00-\u9fff]{1,32}$', alias or ''))


def _allowed_roles_for(manager: dict[str, Any] | None) -> set[str]:
    if manager is None:
        return set()
    if is_super_admin_account(manager):
        return {ROLE_SUPER_ADMIN, ROLE_ORG_ADMIN, ROLE_LEVEL_ADMIN, ROLE_DEVELOPER, ROLE_USER}
    if manager.get('role') == ROLE_ORG_ADMIN:
        return {ROLE_ORG_ADMIN, ROLE_LEVEL_ADMIN, ROLE_USER}
    if manager.get('role') == ROLE_LEVEL_ADMIN:
        return {ROLE_LEVEL_ADMIN, ROLE_USER}
    return set()


def _would_create_level_cycle(levels: list[dict], level_id: str, new_parent_id: str) -> bool:
    if not new_parent_id or new_parent_id == level_id:
        return new_parent_id == level_id
    parent_map = {str(level.get('id') or ''): str(level.get('parent_level_id') or '') for level in levels}
    cursor = new_parent_id
    seen: set[str] = set()
    while cursor and cursor not in seen:
        if cursor == level_id:
            return True
        seen.add(cursor)
        cursor = parent_map.get(cursor, '')
    return False


def _build_hierarchy_tree(users: list[dict], organizations: list[dict], levels: list[dict], current_username: str) -> list[dict]:
    users_by_level: dict[str, list[dict]] = {}
    for user in users:
        org_id = user.get('organization_id') or DEFAULT_ORGANIZATION_ID
        level_id = user.get('level_id') or root_level_id_for_org(org_id)
        users_by_level.setdefault(level_id, []).append(user)

    levels_by_org: dict[str, list[dict]] = {}
    for level in levels:
        levels_by_org.setdefault(level.get('organization_id') or DEFAULT_ORGANIZATION_ID, []).append(level)

    def build_level_node(level: dict, org_id: str, children_map: dict[str, list[dict]]) -> dict:
        level_id = level.get('id') or ''
        level_users = sorted(users_by_level.get(level_id, []), key=lambda u: (u.get('alias') or u.get('username') or ''))
        user_nodes = []
        for user in level_users:
            username = user.get('username') or ''
            user_nodes.append({
                'node_type': 'user',
                'username': username,
                'alias': user.get('alias') or username,
                'role': user.get('role') or ROLE_USER,
                'organization_id': org_id,
                'organization_name': user.get('organization_name') or '',
                'level_id': level_id,
                'can_manage': can_manage_user_account(current_username, username),
            })
        child_levels = [build_level_node(child, org_id, children_map) for child in children_map.get(level_id, [])]
        return {
            'node_type': 'level',
            'id': level_id,
            'name': level.get('name') or '',
            'organization_id': org_id,
            'manager_username': level.get('manager_username') or '',
            'can_manage': can_manage_level(current_username, level_id),
            'children': child_levels + user_nodes,
        }

    tree = []
    for org in organizations:
        org_id = org.get('id') or DEFAULT_ORGANIZATION_ID
        org_levels = [level for level in levels_by_org.get(org_id, [])]
        by_parent: dict[str, list[dict]] = {}
        for level in org_levels:
            parent = level.get('parent_level_id') or ''
            by_parent.setdefault(parent, []).append(level)
        for parent in by_parent:
            by_parent[parent].sort(key=lambda level: (level.get('name') or '', level.get('id') or ''))
        root_levels = by_parent.get('', [])
        org_children = [build_level_node(level, org_id, by_parent) for level in root_levels]
        tree.append({
            'node_type': 'organization',
            'id': org_id,
            'name': org.get('name') or '',
            'description': org.get('description') or '',
            'can_manage': can_manage_organization(current_username, org_id),
            'children': org_children,
        })
    return tree


@admin_bp.route('/api/context', methods=['GET'])
@login_required
def api_admin_context():
    username, acct, error = _require_admin_account()
    if error:
        return error
    assert acct is not None
    accounts = [serialize_account_public(a, username) for a in visible_accounts_for(username, include_self=True)]
    orgs = visible_organizations_for(username)
    levels = list_levels_with_roots()
    visible_org_ids = {org.get('id') for org in orgs}
    levels = [level for level in levels if (level.get('organization_id') or DEFAULT_ORGANIZATION_ID) in visible_org_ids]
    hierarchy = _build_hierarchy_tree(accounts, orgs, levels, username)
    return jsonify({
        'success': True,
        'current_user': serialize_account_public(acct, username),
        'role_labels': ROLE_LABELS,
        'organizations': orgs,
        'levels': levels,
        'users': accounts,
        'hierarchy': hierarchy,
    })


@admin_bp.route('/api/jobs', methods=['GET'])
@login_required
def api_global_jobs():
    _, acct, error = _require_admin_account()
    if error:
        return error
    if not is_super_admin_account(acct):
        return jsonify({
            'success': False,
            'error': '只有超级管理员可以查看全服测试任务',
        }), 403
    try:
        limit = min(100, max(1, int(request.args.get('limit', '20') or 20)))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'limit 必须是整数'}), 400
    cursor = str(request.args.get('cursor') or '').strip()
    before_updated_at = None
    before_job_id = ''
    if cursor:
        try:
            raw = base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4))
            decoded = orjson.loads(raw)
            before_updated_at = float(decoded['updated_at'])
            before_job_id = str(decoded['job_id'])
            if not before_job_id:
                raise ValueError
        except (KeyError, TypeError, ValueError, orjson.JSONDecodeError):
            return jsonify({'success': False, 'error': 'cursor 无效'}), 400
    jobs, has_more = _job_repository().list_global_summaries(
        limit=limit,
        before_updated_at=before_updated_at,
        before_job_id=before_job_id,
    )
    next_cursor = None
    if has_more and jobs:
        next_cursor = base64.urlsafe_b64encode(orjson.dumps({
            'updated_at': jobs[-1]['updated_at'],
            'job_id': jobs[-1]['job_id'],
        })).rstrip(b'=').decode()
    return jsonify({
        'success': True,
        'jobs': jobs,
        'page_size': len(jobs),
        'has_more': has_more,
        'next_cursor': next_cursor,
    })


@admin_bp.route('/api/organizations', methods=['POST'])
@login_required
def api_create_organization():
    username, acct, error = _require_admin_account()
    if error:
        return error
    assert acct is not None
    if not is_super_admin_account(acct):
        return jsonify({'success': False, 'error': '只有超级管理员可以新建机构'}), 403
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    description = (data.get('description') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': '机构名称不能为空'}), 400
    org = normalize_organization({'name': name, 'description': description})
    with organizations_lock:
        organizations = [normalize_organization(o) for o in load_organizations()]
        if any(o.get('id') == org['id'] or o.get('name') == org['name'] for o in organizations):
            return jsonify({'success': False, 'error': '机构已存在'}), 400
        organizations.append(org)
        save_organizations(organizations)
    with levels_lock:
        levels = normalize_levels(load_levels())
        root_id = root_level_id_for_org(org.get('id') or DEFAULT_ORGANIZATION_ID)
        if not any(level.get('id') == root_id for level in levels):
            levels.append({
                'id': root_id,
                'organization_id': org.get('id') or DEFAULT_ORGANIZATION_ID,
                'name': '默认层级',
                'parent_level_id': '',
                'manager_username': '',
            })
            save_levels(levels)
    return jsonify({'success': True, 'organization': org})


@admin_bp.route('/api/organizations/<path:organization_id>', methods=['DELETE'])
@login_required
def api_delete_organization(organization_id):
    username, acct, error = _require_admin_account()
    if error:
        return error
    assert acct is not None
    if not is_super_admin_account(acct):
        return jsonify({'success': False, 'error': '只有超级管理员可以删除机构'}), 403
    data = request.get_json(silent=True) or {}
    admin_password = data.get('admin_password') or ''
    if not admin_password:
        return jsonify({'success': False, 'error': '请输入超级管理员密码'}), 400
    if not verify_password(admin_password, acct.get('salt') or '', acct.get('hash') or ''):
        return jsonify({'success': False, 'error': '超级管理员密码错误'}), 403
    organization_id = (organization_id or '').strip()
    if not organization_id or organization_id == DEFAULT_ORGANIZATION_ID:
        return jsonify({'success': False, 'error': '默认机构不能删除'}), 400
    with accounts_lock:
        accounts = normalize_accounts(load_accounts())
        if any((a.get('organization_id') or DEFAULT_ORGANIZATION_ID) == organization_id for a in accounts):
            return jsonify({'success': False, 'error': '该机构下仍有用户，无法删除'}), 400
    with organizations_lock:
        organizations = [normalize_organization(o) for o in load_organizations()]
        before = len(organizations)
        organizations = [o for o in organizations if o.get('id') != organization_id]
        if len(organizations) == before:
            return jsonify({'success': False, 'error': '机构不存在'}), 404
        save_organizations(organizations)
    with levels_lock:
        levels = normalize_levels(load_levels())
        levels = [level for level in levels if (level.get('organization_id') or DEFAULT_ORGANIZATION_ID) != organization_id]
        save_levels(levels)
    return jsonify({'success': True})


@admin_bp.route('/api/levels', methods=['POST'])
@login_required
def api_create_level():
    username, manager, error = _require_admin_account()
    if error:
        return error
    assert manager is not None
    data = request.get_json(silent=True) or {}
    org_id = (data.get('organization_id') or manager.get('organization_id') or DEFAULT_ORGANIZATION_ID).strip()
    parent_level_id = (data.get('parent_level_id') or '').strip()
    name = (data.get('name') or '').strip()
    if parent_level_id:
        if not can_manage_level(username, parent_level_id):
            return jsonify({'success': False, 'error': '无权在该上级层级下新增子层级'}), 403
    elif not can_manage_organization(username, org_id):
        return jsonify({'success': False, 'error': '无权在该机构新增根层级'}), 403
    with levels_lock:
        levels = normalize_levels(load_levels())
        org_levels = [level for level in levels if (level.get('organization_id') or DEFAULT_ORGANIZATION_ID) == org_id]
        if parent_level_id and not any(level.get('id') == parent_level_id for level in org_levels):
            return jsonify({'success': False, 'error': '上级层级不存在'}), 400
        base = (name or 'level').replace(' ', '_')
        base = re.sub(r'[^\w\u4e00-\u9fff-]', '', base) or 'level'
        level_id = f'{org_id}__{base}'
        suffix = 1
        existed = {level.get('id') for level in levels}
        while level_id in existed:
            suffix += 1
            level_id = f'{org_id}__{base}_{suffix}'
        level = {
            'id': level_id,
            'organization_id': org_id,
            'name': name,
            'parent_level_id': parent_level_id,
            'manager_username': '',
        }
        levels.append(level)
        save_levels(levels)
    return jsonify({'success': True, 'level': level})


@admin_bp.route('/api/levels/<path:level_id>', methods=['PUT'])
@login_required
def api_update_level(level_id):
    username, _, error = _require_admin_account()
    if error:
        return error
    if not can_manage_level(username, level_id):
        return jsonify({'success': False, 'error': '无权管理该层级'}), 403
    data = request.get_json(silent=True) or {}
    with levels_lock:
        levels = normalize_levels(load_levels())
        target = next((level for level in levels if level.get('id') == level_id), None)
        if not target:
            return jsonify({'success': False, 'error': '层级不存在'}), 404
        org_id = target.get('organization_id') or DEFAULT_ORGANIZATION_ID
        if 'name' in data:
            target['name'] = (data.get('name') or '').strip()
        if 'parent_level_id' in data:
            parent_level_id = (data.get('parent_level_id') or '').strip()
            if parent_level_id == level_id:
                return jsonify({'success': False, 'error': '上级层级不能是自己'}), 400
            if parent_level_id:
                parent = next((level for level in levels if level.get('id') == parent_level_id), None)
                if not parent or (parent.get('organization_id') or DEFAULT_ORGANIZATION_ID) != org_id:
                    return jsonify({'success': False, 'error': '上级层级不存在或跨机构'}), 400
                if _would_create_level_cycle(levels, level_id, parent_level_id):
                    return jsonify({'success': False, 'error': '层级移动后会形成环路'}), 400
            target['parent_level_id'] = parent_level_id
        if 'manager_username' in data:
            manager_username = (data.get('manager_username') or '').strip()
            if manager_username and not can_manage_user_account(username, manager_username) and manager_username != username:
                return jsonify({'success': False, 'error': '无权指定该层级管理员'}), 403
            if manager_username:
                with accounts_lock:
                    accounts = normalize_accounts(load_accounts())
                manager_account = next((a for a in accounts if a.get('username') == manager_username), None)
                if manager_account is None:
                    return jsonify({'success': False, 'error': '指定的层级管理员不存在'}), 404
                manager_org = manager_account.get('organization_id') or DEFAULT_ORGANIZATION_ID
                if manager_org != org_id:
                    return jsonify({'success': False, 'error': '层级管理员必须属于同一机构'}), 400
            target['manager_username'] = manager_username
        save_levels(levels)
    return jsonify({'success': True, 'level': target})


@admin_bp.route('/api/levels/<path:level_id>', methods=['DELETE'])
@login_required
def api_delete_level(level_id):
    username, _, error = _require_admin_account()
    if error:
        return error
    if not can_manage_level(username, level_id):
        return jsonify({'success': False, 'error': '无权删除该层级'}), 403
    with levels_lock:
        levels = normalize_levels(load_levels())
        target = next((level for level in levels if level.get('id') == level_id), None)
        if not target:
            return jsonify({'success': False, 'error': '层级不存在'}), 404
        if level_id == root_level_id_for_org(target.get('organization_id') or DEFAULT_ORGANIZATION_ID):
            return jsonify({'success': False, 'error': '默认层级不能删除'}), 400
        child_ids = {level.get('id') for level in levels if (level.get('parent_level_id') or '') == level_id}
        with accounts_lock:
            accounts = normalize_accounts(load_accounts())
            if any((account.get('level_id') or '') == level_id for account in accounts):
                return jsonify({'success': False, 'error': '层级下仍有用户，无法删除'}), 400
            if child_ids:
                return jsonify({'success': False, 'error': '层级下仍有子层级，无法删除'}), 400
        levels = [level for level in levels if level.get('id') != level_id]
        save_levels(levels)
    return jsonify({'success': True})


@admin_bp.route('/api/users', methods=['POST'])
@login_required
def api_create_user():
    username, manager, error = _require_admin_account()
    if error:
        return error
    assert manager is not None
    data = request.get_json(silent=True) or {}
    alias = (data.get('alias') or '').strip()
    password = data.get('password') or ''
    role = (data.get('role') or ROLE_USER).strip()
    parent_username = (data.get('parent_username') or '').strip()
    level_id = (data.get('level_id') or '').strip()
    organization_id = (data.get('organization_id') or manager.get('organization_id') or DEFAULT_ORGANIZATION_ID).strip()
    organization_name = (data.get('organization_name') or '').strip()

    if not _validate_alias(alias):
        return jsonify({'success': False, 'error': '用户名只能包含字母、数字、下划线或汉字，且不超过32字符'}), 400
    if len(password) < 6:
        return jsonify({'success': False, 'error': '密码至少6位'}), 400
    if role not in _allowed_roles_for(manager):
        return jsonify({'success': False, 'error': '不能创建该角色'}), 403
    if not can_manage_organization(username, organization_id):
        return jsonify({'success': False, 'error': '无权在该机构下创建用户'}), 403
    if not level_id:
        level_id = root_level_id_for_org(organization_id)
    levels = list_levels_with_roots()
    target_level = next((level for level in levels if level.get('id') == level_id), None)
    if not target_level or (target_level.get('organization_id') or DEFAULT_ORGANIZATION_ID) != organization_id:
        return jsonify({'success': False, 'error': '层级不存在或不属于目标机构'}), 400
    if not can_manage_level(username, level_id):
        return jsonify({'success': False, 'error': '无权在该层级下创建用户'}), 403
    if parent_username and parent_username == username:
        # allow admins to explicitly set themselves as parent
        pass
    elif manager.get('role') == ROLE_LEVEL_ADMIN:
        parent_username = username
    if (
        manager.get('role') == ROLE_ORG_ADMIN
        and parent_username
        and parent_username != username
        and not can_manage_user_account(username, parent_username)
    ):
        return jsonify({'success': False, 'error': '无权指定该上级用户'}), 403

    org = next((o for o in list_organizations_with_default() if o.get('id') == organization_id), None)
    if org:
        organization_name = org.get('name') or organization_name
    if not organization_name:
        organization_name = DEFAULT_ORGANIZATION_NAME

    with accounts_lock:
        accounts = normalize_accounts(load_accounts())
        if not parent_username:
            levels = list_levels_with_roots()
            level = next((lv for lv in levels if lv.get('id') == level_id), None)
            level_manager = (level or {}).get('manager_username') or ''
            if level_manager:
                parent_username = level_manager
        full_name = next_account_username(accounts, organization_id, alias)
        salt = secrets.token_hex(16)
        account = {
            'username': full_name,
            'alias': alias,
            'salt': salt,
            'hash': hash_password(password, salt),
            'role': role,
            'is_admin': role == ROLE_SUPER_ADMIN,
            'organization_id': organization_id,
            'organization_name': organization_name,
            'level_id': level_id,
            'parent_username': parent_username,
        }
        accounts.append(account)
        save_accounts(accounts)
    return jsonify({'success': True, 'user': serialize_account_public(account, username)})


@admin_bp.route('/api/users/<path:target_username>', methods=['PUT'])
@login_required
def api_update_user(target_username):
    username, manager, error = _require_admin_account()
    if error:
        return error
    assert manager is not None
    if not can_manage_user_account(username, target_username):
        return jsonify({'success': False, 'error': '无权管理该用户'}), 403
    data = request.get_json(silent=True) or {}
    with accounts_lock:
        accounts = normalize_accounts(load_accounts())
        target = next((a for a in accounts if a.get('username') == target_username), None)
        if not target:
            return jsonify({'success': False, 'error': '用户不存在'}), 404
        if 'role' in data:
            role = (data.get('role') or '').strip()
            if role not in _allowed_roles_for(manager):
                return jsonify({'success': False, 'error': '不能设置该角色'}), 403
            target['role'] = role
            target['is_admin'] = role == ROLE_SUPER_ADMIN
        if 'organization_id' in data:
            organization_id = (data.get('organization_id') or DEFAULT_ORGANIZATION_ID).strip()
            if not can_manage_organization(username, organization_id):
                return jsonify({'success': False, 'error': '无权移动到该机构'}), 403
            org = next((o for o in list_organizations_with_default() if o.get('id') == organization_id), None)
            target['organization_id'] = organization_id
            target['organization_name'] = (org or {}).get('name') or data.get('organization_name') or DEFAULT_ORGANIZATION_NAME
            if not target.get('level_id'):
                target['level_id'] = root_level_id_for_org(organization_id)
        if 'level_id' in data:
            level_id = (data.get('level_id') or '').strip()
            if not level_id:
                level_id = root_level_id_for_org(target.get('organization_id') or DEFAULT_ORGANIZATION_ID)
            levels = list_levels_with_roots()
            level = next((lv for lv in levels if lv.get('id') == level_id), None)
            if not level:
                return jsonify({'success': False, 'error': '目标层级不存在'}), 400
            target_org = target.get('organization_id') or DEFAULT_ORGANIZATION_ID
            if (level.get('organization_id') or DEFAULT_ORGANIZATION_ID) != target_org:
                return jsonify({'success': False, 'error': '目标层级与用户机构不一致'}), 400
            if not can_manage_level(username, level_id):
                return jsonify({'success': False, 'error': '无权移动到该层级'}), 403
            target['level_id'] = level_id
        if 'parent_username' in data:
            parent_username = (data.get('parent_username') or '').strip()
            if parent_username == target_username:
                return jsonify({'success': False, 'error': '上级用户不能是自己'}), 400
            if parent_username and parent_username != username and not can_manage_user_account(username, parent_username):
                return jsonify({'success': False, 'error': '无权指定该上级用户'}), 403
            target['parent_username'] = parent_username
        if data.get('password'):
            if len(data['password']) < 6:
                return jsonify({'success': False, 'error': '密码至少6位'}), 400
            salt = secrets.token_hex(16)
            target['salt'] = salt
            target['hash'] = hash_password(data['password'], salt)
        save_accounts(accounts)
    return jsonify({'success': True, 'user': serialize_account_public(target, username)})


@admin_bp.route('/api/users/<path:target_username>', methods=['DELETE'])
@login_required
def api_delete_user(target_username):
    username, _, error = _require_admin_account()
    if error:
        return error
    if target_username == username:
        return jsonify({'success': False, 'error': '不能删除当前登录账号'}), 400
    if not can_manage_user_account(username, target_username):
        return jsonify({'success': False, 'error': '无权删除该用户'}), 403
    with accounts_lock:
        accounts = normalize_accounts(load_accounts())
        target = next((a for a in accounts if a.get('username') == target_username), None)
        if not target:
            return jsonify({'success': False, 'error': '用户不存在'}), 404
        accounts = [a for a in accounts if a.get('username') != target_username]
        for acct in accounts:
            if acct.get('parent_username') == target_username:
                acct['parent_username'] = ''
        save_accounts(accounts)
    deleted_configurations = delete_owner_configurations(target_username)
    return jsonify({'success': True, 'deleted_research_configurations': deleted_configurations})
