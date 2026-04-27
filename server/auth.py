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
)

auth_bp = Blueprint('auth', __name__)

@auth_bp.before_app_request
def _check_login():
    PUBLIC_ENDPOINTS = {'auth.login', 'auth.register', 'auth.api_me', 'core.home', 'static'}
    ep = request.endpoint
    if ep is None or ep in PUBLIC_ENDPOINTS:
        return None
    if not _current_user():
        if request.is_json or request.method != 'GET':
            return jsonify({'success': False, 'error': '请先登录', 'login_required': True}), 401
        # 未登录访问受保护页面 → 回首页并带 next 参数，首页会弹出登录框
        return redirect(f'/?next={request.path}')
    return None

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
    acct = next((a for a in accounts if a['username'] == username), None)
    if acct is None or not _verify_password(password, acct['salt'], acct['hash']):
        return jsonify({'success': False, 'error': '用户名或密码错误'}), 401
    session.permanent = True   # 持久登录，依 app.permanent_session_lifetime 过期
    session['username'] = username
    return jsonify({'success': True, 'username': username, 'is_admin': bool(acct and acct.get('is_admin', False))})

@auth_bp.route('/logout', methods=['POST'])
def logout():
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
    if len(password) < 6:
        return jsonify({'success': False, 'error': '密码至少6位'}), 400
    with _accts_lock:
        accounts = _load_accounts()
        if any(a['username'] == username for a in accounts):
            return jsonify({'success': False, 'error': '用户名已存在'}), 409
        salt = secrets.token_hex(16)
        is_admin = len(accounts) == 0  # 第一个注册的用户自动成为管理员
        accounts.append({'username': username, 'salt': salt, 'hash': _hash_password(password, salt), 'is_admin': is_admin})
        _save_accounts(accounts)
    session.permanent = True
    session['username'] = username
    return jsonify({'success': True, 'username': username, 'is_admin': is_admin})

@auth_bp.route('/api/me')
def api_me():
    username = _current_user()
    is_admin = False
    if username:
        with _accts_lock:
            accounts = _load_accounts()
        acct = next((a for a in accounts if a['username'] == username), None)
        is_admin = bool(acct and acct.get('is_admin', False))
    return jsonify({'username': username, 'is_admin': is_admin})
