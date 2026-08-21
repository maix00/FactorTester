"""
Authentication Blueprint — 登录/登出/注册 + 全局请求认证守卫。

核心职责：
  - before_app_request: 全局认证检查，区分公开端点/已登录/未登录/超时四种情况
  - login: 支持 alias、机构@alias 和完整 username 精确匹配
  - logout: 清理 FactorTester 实例 + session 资源
  - register: 新建用户（需管理员权限）
  - api_me / api_keep_login / api_public_organizations: 前端状态同步 API

PUBLIC_ENDPOINTS: 不要求登录的端点集合，包含文档系统和静态资源。
"""
import re
import secrets
from flask import Blueprint, request, jsonify, render_template, session, redirect
from tools.data.account_manage import (
    accounts_lock, load_accounts, save_accounts,
    verify_password, hash_password,
    normalize_account, serialize_account_public,
    DEFAULT_ORGANIZATION_ID, DEFAULT_ORGANIZATION_NAME,
    ROLE_SUPER_ADMIN, ROLE_USER, ROLE_DEVELOPER,
    list_organizations_with_default, next_account_username, root_level_id_for_org,
)
from server.services.session_runtime import (
    check_session_idle,
    cleanup_session_resource,
    current_user,
    current_user_obj,
    touch_session_activity,
)
from server.services.page_runtime import cleanup_user_pages

auth_bp = Blueprint('auth', __name__)


def _is_public_job_gateway_read() -> bool:
    """Allow only Manager-delegated, read-only job projections.

    The Manager marks this session after validating its loopback capability
    token.  Keeping the exception path-specific prevents the marker from
    becoming a general anonymous login bypass.
    """
    if not session.get('manager_gateway_public_jobs'):
        return False
    if request.method != 'GET':
        return False
    path = request.path
    if path == '/api/jobs':
        return True
    return bool(re.fullmatch(
        r'/api/jobs/[A-Za-z0-9._-]{1,128}'
        r'(?:/result|/artifacts|/supplementals(?:/[A-Za-z0-9._-]{1,128})?)?',
        path,
    ))


def _is_public_graph_gateway_read() -> bool:
    """Allow only Manager-delegated immutable research graph reads."""
    return bool(
        session.get('manager_gateway_public_graph')
        and request.method == 'GET'
        and re.fullmatch(
            r'/api/research-graphs/[^/]+/(?:versions|active)',
            request.path,
        )
    )


def _wants_json_response() -> bool:
    return (
        request.is_json
        or request.method != 'GET'
        or request.accept_mimetypes.best == 'application/json'
    )


@auth_bp.before_app_request
def _check_login():
    PUBLIC_ENDPOINTS = {
        'auth.login', 'auth.register', 'auth.api_me', 'auth.api_keep_login',
        'auth.api_public_organizations', 'auth.logout',
        'core.home',
        'shared.client_release_channel',
        'shared.client_release_beta_appcast',
        'shared.client_release_asset',
        'core.docs', 'core.docs_single_factor',
        'core.docs_price_viewer', 'core.docs_factor_editor',
        'core.docs_data_dictionary',
        'core.docs_dev', 'core.docs_dev_backend', 'core.docs_dev_frontend',
        'core.docs_dev_data_pipeline', 'core.docs_dev_deployment',
        'core.docs_tools', 'core.docs_tool_detail',
        'static',
    }
    ep = request.endpoint
    # 公开端点不要求登录，但已登录用户需更新活动时间
    if ep is None or ep in PUBLIC_ENDPOINTS:
        if current_user():
            touch_session_activity()
        return None

    # Anonymous job list/detail/result/artifact reads are exposed only
    # through the loopback Manager gateway.  Mutations, progress streams,
    # storage and all artifact bytes still require Manager authorization.
    if _is_public_job_gateway_read():
        return None
    if _is_public_graph_gateway_read():
        return None

    # 已登录用户：检查自动登出
    if current_user():
        if check_session_idle():
            # 超时：清理该用户的 tester，清除 session
            user = current_user_obj()
            if user is not None:
                cleanup_user_pages(user)
            cleanup_session_resource(session.get('_sid', ''))
            session.clear()
            if _wants_json_response():
                return jsonify({'success': False, 'error': '长时间无操作，已自动退出', 'login_required': True, 'auto_logout': True}), 401
            return redirect(f'/?next={request.path}&auto_logout=1')
        touch_session_activity()
        return None

    # 未登录
    if _wants_json_response():
        return jsonify({'success': False, 'error': '请先登录', 'login_required': True}), 401
    # 未登录访问受保护页面 → 回首页并带 next 参数，首页会弹出登录框
    return redirect(f'/?next={request.path}')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        # GET /login 直接跳首页（登录入口在首页弹框里）
        return redirect('/')
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not username or not password:
        return jsonify({'success': False, 'error': '用户名和密码不能为空'}), 400
    with accounts_lock:
        accounts = load_accounts()
    # 先精确匹配完整 username，再按 alias 匹配（仅当唯一时成功）。
    acct = next((a for a in accounts if a['username'] == username), None)
    if acct is None:
        candidates = [a for a in accounts if a.get('alias', a['username']) == username]
        if len(candidates) == 1:
            acct = candidates[0]
        elif len(candidates) > 1:
            return jsonify({'success': False, 'error': f'用户名 "{username}" 存在多个账号，请使用完整用户名登录', 'ambiguous': True, 'candidates': [c['username'] for c in candidates]}), 400
    if acct is None or not verify_password(password, acct['salt'], acct['hash']):
        return jsonify({'success': False, 'error': '用户名或密码错误'}), 401
    session.permanent = True   # 持久登录，依 app.permanent_session_lifetime 过期
    session['username'] = acct['username']
    # Native/CLI clients may request persistence atomically with login.  This
    # avoids a transient session window between /login and /api/keep_login.
    # Browser callers that omit the field retain the existing temporary
    # session behavior.
    session['keep_login'] = bool(data.get('keep_login', False))
    touch_session_activity()
    acct = normalize_account(acct)
    return jsonify({
        'success': True,
        'username': acct['username'],
        'alias': acct.get('alias', acct['username']),
        'role': acct.get('role', ROLE_USER),
        'organization_id': acct.get('organization_id', DEFAULT_ORGANIZATION_ID),
        'organization_name': acct.get('organization_name', DEFAULT_ORGANIZATION_NAME),
        'is_admin': bool(acct.get('is_admin') or acct.get('role') == ROLE_SUPER_ADMIN),
        'is_developer': bool(acct.get('is_developer') or acct.get('role') == ROLE_DEVELOPER),
    })

@auth_bp.route('/logout', methods=['POST'])
def logout():
    # 退出前清理该用户的 FactorTester
    user = current_user_obj()
    if user is not None:
        cleanup_user_pages(user)
    # 清理 session 资源记录
    cleanup_session_resource(session.get('_sid', ''))
    session.clear()
    return jsonify({'success': True})





@auth_bp.route('/api/me')
def api_me():
    username = current_user()
    acct_public = None
    if username:
        with accounts_lock:
            accounts = load_accounts()
        acct = next((a for a in accounts if a['username'] == username), None)
        acct_public = serialize_account_public(acct, current_username=username) if acct else None
    return jsonify({
        'username': username,
        'alias': (acct_public or {}).get('alias') if acct_public else None,
        'role': (acct_public or {}).get('role'),
        'organization_id': (acct_public or {}).get('organization_id'),
        'organization_name': (acct_public or {}).get('organization_name'),
        'is_admin': bool((acct_public or {}).get('is_admin')),
        'is_developer': bool((acct_public or {}).get('role') in {ROLE_SUPER_ADMIN, ROLE_DEVELOPER}),
        'keep_login': bool(session.get('keep_login')),
    })

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    organization_id = (data.get('organization_id') or DEFAULT_ORGANIZATION_ID).strip()
    if not username or not password:
        return jsonify({'success': False, 'error': '用户名和密码不能为空'}), 400
    if not re.match(r'^[A-Za-z0-9_\u4e00-\u9fff]{1,32}$', username):
        return jsonify({'success': False, 'error': '用户名只能包含字母、数字、下划线或汉字，且不超过32字符'}), 400
    if len(password) < 6:
        return jsonify({'success': False, 'error': '密码至少6位'}), 400
    org = next((o for o in list_organizations_with_default() if o.get('id') == organization_id), None)
    if not org:
        return jsonify({'success': False, 'error': '机构不存在'}), 400
    with accounts_lock:
        accounts = load_accounts()
        # 新账号 id 格式为 {organization_id}@{alias}@{random_digits}
        full_name = next_account_username(accounts, organization_id, username)
        salt = secrets.token_hex(16)
        role = ROLE_SUPER_ADMIN if len(accounts) == 0 else ROLE_USER
        is_admin = role == ROLE_SUPER_ADMIN  # 第一个注册的用户自动成为超级管理员
        accounts.append({
            'username': full_name,
            'alias': username,
            'salt': salt,
            'hash': hash_password(password, salt),
            'role': role,
            'is_admin': is_admin,
            'organization_id': organization_id,
            'organization_name': org.get('name') or DEFAULT_ORGANIZATION_NAME,
            'level_id': root_level_id_for_org(organization_id),
            'parent_username': '',
        })
        save_accounts(accounts)
    session.permanent = True
    session['username'] = full_name
    session['keep_login'] = bool(data.get('keep_login', False))
    touch_session_activity()
    return jsonify({'success': True, 'username': full_name, 'alias': username, 'role': role, 'is_admin': is_admin})

@auth_bp.route('/api/organizations')
def api_public_organizations():
    """Registration-time organization lookup. Creation remains admin-only."""
    orgs = list_organizations_with_default()
    return jsonify({'success': True, 'organizations': orgs})

@auth_bp.route('/api/keep_login', methods=['POST'])
def api_keep_login():
    """设置当前 session 的 keep_login 状态"""
    if not current_user():
        return jsonify({'success': False, 'error': '请先登录'}), 401
    data = request.get_json(silent=True) or {}
    session['keep_login'] = bool(data.get('keep_login', False))
    touch_session_activity()
    return jsonify({'success': True, 'keep_login': session['keep_login']})


@auth_bp.route('/api/account/password', methods=['POST'])
def api_change_password():
    """Allow the signed-in account to rotate its own password."""
    username = current_user()
    if not username:
        return jsonify({'success': False, 'error': '请先登录'}), 401
    data = request.get_json(silent=True) or {}
    current_password = data.get('current_password') or ''
    new_password = data.get('new_password') or ''
    if not current_password or not new_password:
        return jsonify({'success': False, 'error': '当前密码和新密码不能为空'}), 400
    if len(new_password) < 6:
        return jsonify({'success': False, 'error': '新密码至少6位'}), 400
    if current_password == new_password:
        return jsonify({'success': False, 'error': '新密码不能与当前密码相同'}), 400

    with accounts_lock:
        accounts = load_accounts()
        account = next(
            (item for item in accounts if item.get('username') == username),
            None,
        )
        if account is None or not verify_password(
            current_password,
            account.get('salt') or '',
            account.get('hash') or '',
        ):
            return jsonify({'success': False, 'error': '当前密码错误'}), 400
        salt = secrets.token_hex(16)
        account['salt'] = salt
        account['hash'] = hash_password(new_password, salt)
        save_accounts(accounts)
    return jsonify({'success': True})


def verify_current_user_password(password: str) -> bool:
    """Verify the signed-in account without changing its session."""
    username = current_user()
    if not username or not password:
        return False
    with accounts_lock:
        accounts = load_accounts()
    account = next(
        (item for item in accounts if item.get('username') == username),
        None,
    )
    return bool(account) and verify_password(
        password,
        account.get('salt') or '',
        account.get('hash') or '',
    )
