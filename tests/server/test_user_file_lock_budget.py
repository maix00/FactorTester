"""用户写锁必须有等待上限：一次卡死的请求不能永久锁死该用户的全部操作。"""

from __future__ import annotations

import threading
import time

import pytest

from server.services import session_runtime


def test_acquires_normally():
    with session_runtime.user_file_lock_budget("probe-user", timeout=2) as lock:
        assert lock.locked()


def test_releases_after_use():
    with session_runtime.user_file_lock_budget("probe-user-2", timeout=2):
        pass
    assert not session_runtime.get_user_file_lock("probe-user-2").locked()


def test_fails_loudly_instead_of_waiting_forever():
    holder = session_runtime.get_user_file_lock("probe-user-3")
    holder.acquire()
    try:
        started = time.monotonic()
        with pytest.raises(TimeoutError) as excinfo:
            with session_runtime.user_file_lock_budget("probe-user-3", timeout=0.3):
                pass
        elapsed = time.monotonic() - started
        assert elapsed < 3, "必须在等待上限附近失败，不能无限等"
        assert "等待用户写锁超时" in str(excinfo.value)
    finally:
        holder.release()


def test_lock_holder_is_named_while_held():
    with session_runtime.user_file_lock_budget("probe-user-4", timeout=2):
        assert session_runtime.user_file_lock_owners.get("probe-user-4")
