"""
Admin Blueprint: organization and user hierarchy management.
"""
import re
import secrets
from flask import Blueprint, request, jsonify, render_template

from server.services.accounts import (
    accounts_lock, load_accounts, save_accounts,
    organizations_lock, load_organizations, save_organizations,
    normalize_accounts, normalize_organization, list_organizations_with_default,
    visible_accounts_for, visible_organizations_for,
    serialize_account_public, get_account,
    hash_password,
    DEFAULT_ORGANIZATION_ID, DEFAULT_ORGANIZATION_NAME,
    ROLE_SUPER_ADMIN, ROLE_ORG_ADMIN, ROLE_LEVEL_ADMIN, ROLE_USER,
    is_super_admin_account, is_org_admin_account, is_level_admin_account,
    can_manage_user_account, can_manage_organization,
    next_account_username,
)
from server.services.http_auth import login_required
from server.services.runtime_state import require_user

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

ROLE_LABELS = {
    ROLE_SUPER_ADMIN: '超级管理员',
    ROLE_ORG_ADMIN: '机构管理员',
    ROLE_LEVEL_ADMIN: '层级管理员',
    ROLE_USER: '普通用户',
}


def _require_admin_account():
    username = require_user()
    acct = get_account(username)
    if not (is_super_admin_account(acct) or is_org_admin_account(acct) or is_level_admin_account(acct)):
        return username, acct, (jsonify({'success': False, 'error': '需要管理员权限'}), 403)
    return username, acct, None


def _validate_alias(alias: str) -> bool:
    return bool(re.match(r'^[A-Za-z0-9_\u4e00-\u9fff]{1,32}$', alias or ''))


def _allowed_roles_for(manager: dict) -> set[str]:
    if is_super_admin_account(manager):
        return {ROLE_SUPER_ADMIN, ROLE_ORG_ADMIN, ROLE_LEVEL_ADMIN, ROLE_USER}
    if manager.get('role') == ROLE_ORG_ADMIN:
        return {ROLE_ORG_ADMIN, ROLE_LEVEL_ADMIN, ROLE_USER}
    if manager.get('role') == ROLE_LEVEL_ADMIN:
        return {ROLE_LEVEL_ADMIN, ROLE_USER}
    return set()


@admin_bp.route('/users', methods=['GET'])
@login_required
def users_page():
    _, _, error = _require_admin_account()
    if error:
        return error
    return render_template('admin_users.html')


@admin_bp.route('/api/context', methods=['GET'])
@login_required
def api_admin_context():
    username, acct, error = _require_admin_account()
    if error:
        return error
    accounts = [serialize_account_public(a, username) for a in visible_accounts_for(username, include_self=True)]
    orgs = visible_organizations_for(username)
    return jsonify({
        'success': True,
        'current_user': serialize_account_public(acct, username),
        'role_labels': ROLE_LABELS,
        'organizations': orgs,
        'users': accounts,
    })


@admin_bp.route('/api/organizations', methods=['POST'])
@login_required
def api_create_organization():
    username, acct, error = _require_admin_account()
    if error:
        return error
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
    return jsonify({'success': True, 'organization': org})


@admin_bp.route('/api/users', methods=['POST'])
@login_required
def api_create_user():
    username, manager, error = _require_admin_account()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    alias = (data.get('alias') or '').strip()
    password = data.get('password') or ''
    role = (data.get('role') or ROLE_USER).strip()
    parent_username = (data.get('parent_username') or '').strip()
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
    if manager.get('role') == ROLE_LEVEL_ADMIN:
        parent_username = username
    if manager.get('role') == ROLE_ORG_ADMIN and parent_username and not can_manage_user_account(username, parent_username):
        return jsonify({'success': False, 'error': '无权指定该上级用户'}), 403

    org = next((o for o in list_organizations_with_default() if o.get('id') == organization_id), None)
    if org:
        organization_name = org.get('name') or organization_name
    if not organization_name:
        organization_name = DEFAULT_ORGANIZATION_NAME

    with accounts_lock:
        accounts = normalize_accounts(load_accounts())
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
        if 'parent_username' in data:
            parent_username = (data.get('parent_username') or '').strip()
            if parent_username == target_username:
                return jsonify({'success': False, 'error': '上级用户不能是自己'}), 400
            if parent_username and not can_manage_user_account(username, parent_username):
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
    return jsonify({'success': True})
