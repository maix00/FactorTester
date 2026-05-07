"""
Authentication Blueprint: login, logout, register, /api/me, and the
before_app_request auth guard that previously lived on app directly.
"""
import re
from flask import Blueprint, request, jsonify, render_template, session, redirect
from .shared import (
    _accts_lock, _load_accounts, _save_accounts,
    _verify_password, _hash_password,
    _current_user, secrets,
    _touch_session_activity, _check_session_idle, _cleanup_session_resource,
    _current_user_obj, _factor_testers_lock, factor_testers,
)

auth_bp = Blueprint('auth', __name__)

@auth_bp.before_app_request
def _check_login():
    PUBLIC_ENDPOINTS = {'auth.login', 'auth.register', 'auth.api_me', 'auth.api_keep_login', 'auth.logout', 'core.home', 'core.docs', 'core.docs_tools', 'core.docs_tool_detail', 'core.price_viewer', 'static',
                        'custom_factors.editor_page',
                        'shared.list_product_names', 'shared.get_product_tree', 'shared.get_price_data', 'shared.get_products'}
    ep = request.endpoint
    # 公开端点不要求登录，但已登录用户需更新活动时间
    if ep is None or ep in PUBLIC_ENDPOINTS:
        if _current_user():
            _touch_session_activity()
        return None

    # 已登录用户：检查自动登出
    if _current_user():
        if _check_session_idle():
            # 超时：清理该用户的 tester，清除 session
            user = _current_user_obj()
            if user is not None:
                user.cleanup_testers()
                with _factor_testers_lock:
                    factor_testers[:] = [t for t in factor_testers if t.user is not user or t not in user._testers]
            _cleanup_session_resource(session.get('_sid', ''))
            session.clear()
            if request.is_json or request.method != 'GET':
                return jsonify({'success': False, 'error': '长时间无操作，已自动退出', 'login_required': True, 'auto_logout': True}), 401
            return redirect(f'/?next={request.path}&auto_logout=1')
        _touch_session_activity()
        return None

    # 未登录
    if request.is_json or request.method != 'GET':
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
    with _accts_lock:
        accounts = _load_accounts()
    # 先精确匹配 username（如 '张三@1'），再按 alias 匹配（如 '张三'——仅当唯一时成功）
    acct = next((a for a in accounts if a['username'] == username), None)
    if acct is None:
        candidates = [a for a in accounts if a.get('alias', a['username']) == username]
        if len(candidates) == 1:
            acct = candidates[0]
        elif len(candidates) > 1:
            return jsonify({'success': False, 'error': f'用户名 "{username}" 存在多个账号，请使用完整名称登录（如 {username}@1、{username}@2）', 'ambiguous': True, 'candidates': [c['username'] for c in candidates]}), 400
    if acct is None or not _verify_password(password, acct['salt'], acct['hash']):
        return jsonify({'success': False, 'error': '用户名或密码错误'}), 401
    session.permanent = True   # 持久登录，依 app.permanent_session_lifetime 过期
    session['username'] = acct['username']
    # 默认不保持登录（用户可登录后手动勾选）
    session['keep_login'] = False
    _touch_session_activity()
    return jsonify({'success': True, 'username': acct['username'], 'alias': acct.get('alias', acct['username']), 'is_admin': bool(acct.get('is_admin', False))})

@auth_bp.route('/logout', methods=['POST'])
def logout():
    from server.shared import _current_user_obj, _factor_testers_lock, factor_testers, _cleanup_session_resource
    # 退出前清理该用户的 FactorTester
    user = _current_user_obj()
    if user is not None:
        user.cleanup_testers()
        # 从全局列表中移除已被清理的 tester
        with _factor_testers_lock:
            factor_testers[:] = [t for t in factor_testers if t.user is not user or t not in user._testers]
    # 清理 session 资源记录
    _cleanup_session_resource(session.get('_sid', ''))
    session.clear()
    return jsonify({'success': True})

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not username or not password:
        return jsonify({'success': False, 'error': '用户名和密码不能为空'}), 400
    if not re.match(r'^[A-Za-z0-9_\u4e00-\u9fff]{1,32}$', username):
        return jsonify({'success': False, 'error': '用户名只能包含字母、数字、下划线或汉字，且不超过32字符'}), 400
    if '$' in username:
        return jsonify({'success': False, 'error': '用户名不能包含 $ 符号'}), 400
    if len(password) < 6:
        return jsonify({'success': False, 'error': '密码至少6位'}), 400
    with _accts_lock:
        accounts = _load_accounts()
        # 同名用户自动分配序列号：username@serial
        same_name = [a for a in accounts if a.get('alias', a['username']) == username]
        serial = max((int(a['username'].rsplit('@', 1)[1]) for a in same_name if '@' in a['username'] and a['username'].rsplit('@', 1)[1].isdigit()), default=0) + 1
        full_name = f'{username}@{serial}'
        salt = secrets.token_hex(16)
        is_admin = len(accounts) == 0  # 第一个注册的用户自动成为管理员
        accounts.append({'username': full_name, 'alias': username, 'salt': salt, 'hash': _hash_password(password, salt), 'is_admin': is_admin})
        _save_accounts(accounts)
    session.permanent = True
    session['username'] = full_name
    return jsonify({'success': True, 'username': full_name, 'alias': username, 'is_admin': is_admin})

@auth_bp.route('/api/me')
def api_me():
    username = _current_user()
    is_admin = False
    alias = None
    if username:
        with _accts_lock:
            accounts = _load_accounts()
        acct = next((a for a in accounts if a['username'] == username), None)
        is_admin = bool(acct and acct.get('is_admin', False))
        alias = (acct.get('alias') if acct else None) or username
    return jsonify({'username': username, 'alias': alias, 'is_admin': is_admin, 'keep_login': bool(session.get('keep_login'))})

@auth_bp.route('/api/keep_login', methods=['POST'])
def api_keep_login():
    """设置当前 session 的 keep_login 状态"""
    if not _current_user():
        return jsonify({'success': False, 'error': '请先登录'}), 401
    data = request.get_json(silent=True) or {}
    session['keep_login'] = bool(data.get('keep_login', False))
    _touch_session_activity()
    return jsonify({'success': True, 'keep_login': session['keep_login']})
