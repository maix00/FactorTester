"""Session-scoped runtime state helpers."""

from __future__ import annotations

from contextlib import contextmanager

from typing import Any
import threading
import uuid

from flask import session

from tools.data.account_manage import accounts_lock, load_accounts


user_file_locks: dict[str, threading.Lock] = {}
user_file_locks_meta = threading.Lock()
# username -> (owner_thread_ident, acquired_at)，用于识别「持有线程已消失」的泄漏锁
user_file_lock_owners: dict[str, tuple[int, float]] = {}
user_file_lock_owners: dict[str, str] = {}

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


def current_user() -> str | None:
    return session.get('username')


def current_user_obj():
    username = current_user()
    if not username:
        return None
    return user_obj_for_name(username)


def user_obj_for_name(username: str):
    """Build a User domain object without requiring a Flask request context."""
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





@contextmanager
def user_file_lock_budget(username: str, timeout: float = 20.0):
    """Bounded wait for the user's write lock.

    The lock is held across a read/modify/write of the user's library and is a
    plain non-reentrant ``threading.Lock``.  When one request gets stuck while
    holding it, every later request for that user waits forever: the caller
    (a proxied request) gives up after about twelve seconds, but the server-side
    thread keeps holding the lock, so the failure looks permanent until the
    container is restarted.  Waiting without a bound turns one slow request into
    an outage for the whole user, so the wait now fails loudly instead, and the
    message names the lock holder so the cause is visible in the logs.
    """
    import time

    lock = get_user_file_lock(username)
    deadline = time.monotonic() + max(0.1, float(timeout))
    if not lock.acquire(timeout=max(0.1, float(timeout))):
        owner = user_file_lock_owners.get(username)
        if owner is not None and not _thread_is_alive(owner[0]):
            # 持有线程已经消失（例如被前端服务器中止），锁被永久泄漏。可以跨线程
            # release 非可重入锁，所以这里回收它；否则该用户的库操作会一直到重启才恢复。
            try:
                lock.release()
            except RuntimeError:
                pass
            if not lock.acquire(timeout=max(0.1, float(timeout))):
                raise TimeoutError(
                    f"等待用户写锁超时（{timeout:.0f}s），且泄漏锁回收失败：{username}"
                )
        else:
            raise TimeoutError(
                f"等待用户写锁超时（{timeout:.0f}s）：{username}"
                + (f"，当前持有者线程 {owner[0]}" if owner else "，持有者未知")
            )
    user_file_lock_owners[username] = (threading.get_ident(), time.monotonic())
    try:
        yield lock
    finally:
        user_file_lock_owners.pop(username, None)
        lock.release()


def _thread_is_alive(ident: int) -> bool:
    """该线程是否仍在运行（用于识别被中止后留下的泄漏锁）。"""

    return any(
        thread.ident == ident and thread.is_alive()
        for thread in threading.enumerate()
    )


def get_user_file_lock(username: str) -> threading.Lock:
    with user_file_locks_meta:
        if username not in user_file_locks:
            user_file_locks[username] = threading.Lock()
        return user_file_locks[username]
