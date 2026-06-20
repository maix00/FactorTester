"""Session-scoped runtime state helpers."""

from __future__ import annotations

from typing import Any
import threading
import uuid

from flask import session

from tools.data.account_manage import accounts_lock, load_accounts
from server.modules.shared.param_config import normalize_param_rows


params_store: dict = {}
params_store_lock = threading.Lock()
user_file_locks: dict[str, threading.Lock] = {}
user_file_locks_meta = threading.Lock()

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
    if session.get('keep_login'):
        return
    sid = get_session_id()
    try:
        from tools.data.cache.IdleResourceManager import IdleResourceManager
        IdleResourceManager.get_instance().registry.record_use(session_resource_id(sid))
    except Exception:
        pass


def check_session_idle() -> bool:
    if session.get('keep_login'):
        return False
    sid = session.get('_sid')
    if sid is None:
        return False
    try:
        from tools.data.cache.IdleResourceManager import IdleResourceManager
        idle_list = IdleResourceManager.get_instance().registry.get_idle_resources(SESSION_IDLE_TIMEOUT)
        return session_resource_id(sid) in idle_list
    except Exception:
        return False


def cleanup_session_resource(sid: str) -> None:
    try:
        from tools.data.cache.IdleResourceManager import IdleResourceManager
        IdleResourceManager.get_instance().registry.remove(session_resource_id(sid))
    except Exception:
        pass
    with params_store_lock:
        keys_to_remove = [key for key in params_store if key[0] == sid]
        for key in keys_to_remove:
            params_store.pop(key, None)


def current_user() -> str | None:
    return session.get('username')


def current_user_obj():
    username = current_user()
    if not username:
        return None
    from tools.data.account_manage import User
    with accounts_lock:
        accounts = load_accounts()
    acct = next((a for a in accounts if a['username'] == username), None)
    is_admin = bool(acct and acct.get('is_admin', False))
    return User(name=username, is_admin=is_admin)


def require_user() -> str:
    username = session.get('username')
    assert username is not None
    return username


def get_session_params(ff_alias: str, ff) -> list:
    store_key = (get_session_id(), ff_alias)
    with params_store_lock:
        stored = list(params_store.get(store_key, []))
    if not stored:
        return stored
    valid_aliases = {param.alias for param in getattr(ff, 'params', [])}
    pruned = [
        {key: value for key, value in row.items() if key in valid_aliases}
        for row in stored
        if isinstance(row, dict)
    ]
    try:
        normalized = normalize_param_rows(ff, pruned)
    except Exception:
        normalized = []
    if normalized != stored:
        with params_store_lock:
            params_store[store_key] = list(normalized)
    return normalized


def save_session_params(ff_alias: str, params_list: list) -> None:
    store_key = (get_session_id(), ff_alias)
    with params_store_lock:
        params_store[store_key] = list(params_list)


def get_user_file_lock(username: str) -> threading.Lock:
    with user_file_locks_meta:
        if username not in user_file_locks:
            user_file_locks[username] = threading.Lock()
        return user_file_locks[username]
