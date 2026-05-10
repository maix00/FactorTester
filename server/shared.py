"""
Shared global state and utility functions used across all server blueprints.
No Flask routes live here – only state, helpers, and the login_required decorator.
"""
from typing import TYPE_CHECKING, Any, Optional
import sys, os, threading, time, uuid
from functools import wraps
from flask import request, jsonify, session, redirect

import sys as _sys
# Make project root importable when this module is loaded from server/ sub-package
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in _sys.path:
    _sys.path.insert(0, _project_root)

from tools.factors.FactorFamily import FactorFamily as _FactorFamilyForSettingsInit  # noqa: F401
import Settings as Settings
import pandas as pd
from tools import DataColumn  # noqa: F401 – side-effect import used elsewhere
from server.services.user_storage import (
    DATA_DIR as _DATA_DIR,
    USERS_DIR as _USERS_DIR,
    load_user_templates,
    new_template_id,
    save_user_templates,
    user_data_dir,
    user_template_path,
)
from server.services.accounts import accounts_lock, load_accounts

if TYPE_CHECKING:
    from tools.factors import FactorTester

# ─── Submission list (FactorTester instances) ─────────────────────────────────
factor_testers: list = []
_factor_testers_lock = threading.Lock()
def get_factor_tester(alias: str, caller: Optional[Any] = None) -> 'FactorTester':
    with _factor_testers_lock:
        target_suffix = f":{alias}"
        tester = next((t for t in factor_testers if t.alias == str(alias) or t.alias.endswith(target_suffix)), None)
    assert tester is not None, f"{str(caller) + ': ' if caller is not None else ''}未找到对应的测试器实例"
    return tester

# ─── Per-page time range store ────────────────────────────────────────────────
# 按 page_uuid 隔离时间范围，避免同一用户的不同 tab 互相覆盖。
# key = page_uuid (前端在 set_time_range 时获取，后续 submit 时传回)
# value = (start, end, start_calc) 三元组
_MAX_PAGE_UUIDS = 500  # 每个 session 的 page_uuid 上限

_page_time_store: dict = {}  # page_uuid → (start, end, start_calc)
_page_time_store_lock = threading.Lock()


def get_default_time():
    """从 Settings 获取默认时间范围。永远可用，不依赖用户操作。"""
    start = Settings.default_test_start_date
    end   = Settings.default_test_end_date
    if start is None:
        start = pd.Timestamp('2025-01-02', tz='Asia/Shanghai')
    if end is None:
        end = pd.Timestamp('2025-05-31', tz='Asia/Shanghai')
    return start, end


def get_current_time(page_uuid: Optional[str] = None):
    """获取当前页面绑定的运行时时间范围。

    如果 page_uuid 有效且之前通过 set_time_range 设置过，返回该页面的时间；
    否则返回 Settings 默认值。
    """
    if page_uuid:
        with _page_time_store_lock:
            entry = _page_time_store.get(page_uuid)
            if entry is not None:
                return entry  # (start, end, start_calc)
    start, end = get_default_time()
    return start, end, start


def _set_runtime_time(page_uuid: str, start, end, start_calc=None):
    """写入 page_uuid 对应的运行时时间范围（由 set_time_range 路由调用）。"""
    if start_calc is None:
        start_calc = start
    with _page_time_store_lock:
        if page_uuid not in _page_time_store and len(_page_time_store) >= _MAX_PAGE_UUIDS:
            # 超过上限：清理最旧的一半
            keys_to_remove = list(_page_time_store.keys())[:len(_page_time_store) // 2]
            for k in keys_to_remove:
                _page_time_store.pop(k, None)
        _page_time_store[page_uuid] = (start, end, start_calc)

# ─── Per-session params store ─────────────────────────────────────────────────
_params_store: dict = {}  # key: (session_id, ff_alias) → list of param dicts
_params_store_lock = threading.Lock()

# ─── Auto-logout via IdleResourceManager ─────────────────────────────────────
# session 空闲超时通过 IdleResourceManager 的 registry 来追踪。
# 每次请求 touch，_check_login 检查 registry 中是否超时。
SESSION_IDLE_NAMESPACE = "flask_session"
SESSION_IDLE_TIMEOUT = 600  # 10 分钟


def _session_resource_id(sid: str) -> str:
    return f"{SESSION_IDLE_NAMESPACE}:{sid}"


def _touch_session_activity() -> None:
    """记录当前 session 的活动时间。"""
    if session.get('keep_login'):
        return
    sid = _get_session_id()
    try:
        from tools.base.IdleResourceManager import IdleResourceManager
        IdleResourceManager.get_instance().registry.record_use(_session_resource_id(sid))
    except Exception:
        pass


def _check_session_idle() -> bool:
    """检查当前 session 是否空闲超时。返回 True 表示已超时需退出。"""
    if session.get('keep_login'):
        return False
    sid = session.get('_sid')
    if sid is None:
        return False
    try:
        from tools.base.IdleResourceManager import IdleResourceManager
        rid = _session_resource_id(sid)
        idle_list = IdleResourceManager.get_instance().registry.get_idle_resources(SESSION_IDLE_TIMEOUT)
        return rid in idle_list
    except Exception:
        return False


def _cleanup_session_resource(sid: str) -> None:
    """从 registry 和 params_store 中清理指定 session。"""
    try:
        from tools.base.IdleResourceManager import IdleResourceManager
        IdleResourceManager.get_instance().registry.remove(_session_resource_id(sid))
    except Exception:
        pass
    with _params_store_lock:
        keys_to_remove = [k for k in _params_store if k[0] == sid]
        for k in keys_to_remove:
            _params_store.pop(k, None)

def _get_session_id() -> str:
    sid = session.get('_sid')
    if sid is None:
        sid = uuid.uuid4().hex
        session['_sid'] = sid
    return sid

def _get_session_params(ff_alias: str, ff) -> list:
    store_key = (_get_session_id(), ff_alias)
    with _params_store_lock:
        return list(_params_store.get(store_key, []))

def _save_session_params(ff_alias: str, params_list: list):
    store_key = (_get_session_id(), ff_alias)
    with _params_store_lock:
        _params_store[store_key] = list(params_list)

# ─── User-scoped file locks ───────────────────────────────────────────────────
_user_file_locks: dict = {}
_user_file_locks_meta = threading.Lock()

def _get_user_file_lock(username: str) -> threading.Lock:
    with _user_file_locks_meta:
        if username not in _user_file_locks:
            _user_file_locks[username] = threading.Lock()
        return _user_file_locks[username]

def _current_user() -> str | None:
    return session.get('username')

def _current_user_obj():
    """返回当前登录用户的 User 实例（None 若未登录）。"""
    username = _current_user()
    if not username:
        return None
    from tools.base.User import User
    with accounts_lock:
        accounts = load_accounts()
    acct = next((a for a in accounts if a['username'] == username), None)
    is_admin = bool(acct and acct.get('is_admin', False))
    return User(name=username, is_admin=is_admin)

def _require_user() -> str:
    """Return current username. Only call within @login_required routes."""
    u = session.get('username')
    assert u is not None
    return u

def _user_data_dir(username: str) -> str:
    return user_data_dir(username)

def _user_tpl_path(username: str, kind: str, ff_alias: str | None = None, scope_key: str | None = None) -> str:
    """返回模板文件路径。
    
    - scope_key 是模板存储隔离键，不绑定具体业务含义。
      单因子测试可用因子家族 alias；因子库可用 user_id。
      如果提供了 scope_key，模板按 scope_key 隔离存储到 {kind}_templates/{scope_key}.json
    - 否则兼容旧行为：ff_alias 仅对 params 类型有效，其他类型存到 {kind}_templates.json
    """
    return user_template_path(username, kind, ff_alias, scope_key=scope_key)

def _load_user_tpls(username: str, kind: str, ff_alias: str | None = None, scope_key: str | None = None) -> list:
    return load_user_templates(username, kind, ff_alias, scope_key=scope_key)

def _save_user_tpls(username: str, kind: str, templates: list, ff_alias: str | None = None, scope_key: str | None = None):
    save_user_templates(username, kind, templates, ff_alias, scope_key=scope_key)

def _new_tpl_id() -> str:
    return new_template_id()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _current_user():
            if request.is_json or request.method != 'GET':
                return jsonify({'success': False, 'error': '请先登录', 'login_required': True}), 401
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated
