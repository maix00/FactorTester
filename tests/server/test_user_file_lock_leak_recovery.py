"""持有线程消失后留下的泄漏锁必须能被回收，否则该用户库操作会一直到重启才恢复。"""

from __future__ import annotations

import threading

import pytest

from server.services import session_runtime


def test_live_holder_still_blocks():
    user = "leak-live-holder"
    lock = session_runtime.get_user_file_lock(user)
    lock.acquire()
    session_runtime.user_file_lock_owners[user] = (threading.get_ident(), 0.0)
    try:
        with pytest.raises(TimeoutError) as excinfo:
            with session_runtime.user_file_lock_budget(user, timeout=0.3):
                pass
        assert "等待用户写锁超时" in str(excinfo.value)
    finally:
        session_runtime.user_file_lock_owners.pop(user, None)
        lock.release()


def test_leaked_lock_from_a_dead_thread_is_recovered():
    user = "leak-dead-holder"
    lock = session_runtime.get_user_file_lock(user)
    holder_ident: list[int] = []

    def holder() -> None:
        lock.acquire()
        holder_ident.append(threading.get_ident())
        # 模拟被前端服务器中止：线程结束但从不释放锁

    thread = threading.Thread(target=holder)
    thread.start()
    thread.join()
    assert not thread.is_alive()
    session_runtime.user_file_lock_owners[user] = (holder_ident[0], 0.0)
    try:
        with session_runtime.user_file_lock_budget(user, timeout=0.4):
            pass
        assert not lock.locked(), "回收后应处于未持有状态"
    finally:
        session_runtime.user_file_lock_owners.pop(user, None)
