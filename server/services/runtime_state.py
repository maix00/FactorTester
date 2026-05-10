"""Process-local runtime state for Flask requests and factor-test sessions.

This is intentionally different from `server.modules.shared`, which is a Flask
blueprint package for routes shared by frontend modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional
import threading
import uuid

from flask import session

from tools.factors.FactorFamily import FactorFamily as _FactorFamilyForSettingsInit  # noqa: F401
import Settings as Settings
import pandas as pd
from server.services.accounts import accounts_lock, load_accounts

if TYPE_CHECKING:
    from tools.factors import FactorTester


factor_testers: list = []
factor_testers_lock = threading.Lock()


def alias_matches_submission_id(alias: str, submission_id: str | int | None, allow_suffix: bool = True) -> bool:
    """Return True if tester alias matches submission_id.

    Alias format may be either:
    - core id: "123456"
    - namespaced id: "<username>:123456"
    """
    if submission_id is None:
        return False
    sid = str(submission_id)
    if alias == sid:
        return True
    if allow_suffix:
        return alias.endswith(f":{sid}")
    return False


def find_factor_tester(submission_id: str | int | None, allow_suffix: bool = True):
    """Find tester by submission id. Return None when not found."""
    with factor_testers_lock:
        return next(
            (
                t for t in factor_testers
                if alias_matches_submission_id(getattr(t, 'alias', ''), submission_id, allow_suffix=allow_suffix)
            ),
            None,
        )


def get_factor_tester(alias: str, caller: Optional[Any] = None) -> 'FactorTester':
    tester = find_factor_tester(alias, allow_suffix=True)
    assert tester is not None, f"{str(caller) + ': ' if caller is not None else ''}未找到对应的测试器实例"
    return tester


MAX_PAGE_UUIDS = 500
page_time_store: dict = {}
page_time_store_lock = threading.Lock()


def get_default_time():
    """从 Settings 获取默认时间范围。永远可用，不依赖用户操作。"""
    start = Settings.default_test_start_date
    end = Settings.default_test_end_date
    if start is None:
        start = pd.Timestamp('2025-01-02', tz='Asia/Shanghai')
    if end is None:
        end = pd.Timestamp('2025-05-31', tz='Asia/Shanghai')
    return start, end


def get_current_time(page_uuid: Optional[str] = None):
    """获取当前页面绑定的运行时时间范围，否则返回 Settings 默认值。"""
    if page_uuid:
        with page_time_store_lock:
            entry = page_time_store.get(page_uuid)
            if entry is not None:
                return entry
    start, end = get_default_time()
    return start, end, start


def set_runtime_time(page_uuid: str, start, end, start_calc=None):
    """写入 page_uuid 对应的运行时时间范围（由 set_time_range 路由调用）。"""
    if start_calc is None:
        start_calc = start
    with page_time_store_lock:
        if page_uuid not in page_time_store and len(page_time_store) >= MAX_PAGE_UUIDS:
            keys_to_remove = list(page_time_store.keys())[:len(page_time_store) // 2]
            for key in keys_to_remove:
                page_time_store.pop(key, None)
        page_time_store[page_uuid] = (start, end, start_calc)


params_store: dict = {}
params_store_lock = threading.Lock()

SESSION_IDLE_NAMESPACE = "flask_session"
SESSION_IDLE_TIMEOUT = 600


def session_resource_id(sid: str) -> str:
    return f"{SESSION_IDLE_NAMESPACE}:{sid}"


def get_session_id() -> str:
    sid = session.get('_sid')
    if sid is None:
        sid = uuid.uuid4().hex
        session['_sid'] = sid
    return sid


def touch_session_activity() -> None:
    """记录当前 session 的活动时间。"""
    if session.get('keep_login'):
        return
    sid = get_session_id()
    try:
        from tools.base.IdleResourceManager import IdleResourceManager
        IdleResourceManager.get_instance().registry.record_use(session_resource_id(sid))
    except Exception:
        pass


def check_session_idle() -> bool:
    """检查当前 session 是否空闲超时。返回 True 表示已超时需退出。"""
    if session.get('keep_login'):
        return False
    sid = session.get('_sid')
    if sid is None:
        return False
    try:
        from tools.base.IdleResourceManager import IdleResourceManager
        idle_list = IdleResourceManager.get_instance().registry.get_idle_resources(SESSION_IDLE_TIMEOUT)
        return session_resource_id(sid) in idle_list
    except Exception:
        return False


def cleanup_session_resource(sid: str) -> None:
    """从 registry 和 params_store 中清理指定 session。"""
    try:
        from tools.base.IdleResourceManager import IdleResourceManager
        IdleResourceManager.get_instance().registry.remove(session_resource_id(sid))
    except Exception:
        pass
    with params_store_lock:
        keys_to_remove = [key for key in params_store if key[0] == sid]
        for key in keys_to_remove:
            params_store.pop(key, None)


def get_session_params(ff_alias: str, ff) -> list:
    store_key = (get_session_id(), ff_alias)
    with params_store_lock:
        return list(params_store.get(store_key, []))


def save_session_params(ff_alias: str, params_list: list):
    store_key = (get_session_id(), ff_alias)
    with params_store_lock:
        params_store[store_key] = list(params_list)


user_file_locks: dict = {}
user_file_locks_meta = threading.Lock()


def get_user_file_lock(username: str) -> threading.Lock:
    with user_file_locks_meta:
        if username not in user_file_locks:
            user_file_locks[username] = threading.Lock()
        return user_file_locks[username]


def current_user() -> str | None:
    return session.get('username')


def current_user_obj():
    """返回当前登录用户的 User 实例（None 若未登录）。"""
    username = current_user()
    if not username:
        return None
    from tools.base.User import User
    with accounts_lock:
        accounts = load_accounts()
    acct = next((a for a in accounts if a['username'] == username), None)
    is_admin = bool(acct and acct.get('is_admin', False))
    return User(name=username, is_admin=is_admin)


def require_user() -> str:
    """Return current username. Only call within @login_required routes."""
    username = session.get('username')
    assert username is not None
    return username
