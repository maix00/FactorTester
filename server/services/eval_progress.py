"""求值进度服务（线程安全）

为任何调用 FactorExpr.evaluate() 的场景提供统一的节点级进度统计。
用法：

    from server.services.eval_progress import setup, teardown, count_nodes

    total = sum(count_nodes(f._expr) for f in factors)
    setup(total, lambda c, t: q.put(event))

    try:
        ... # 执行 evaluate()
    finally:
        teardown()
"""
from __future__ import annotations

import threading
from typing import Callable

from tools.factors.FactorExpr import FactorExpr

# ── 全局状态（线程安全） ──
_lock = threading.Lock()
_completed: int = 0
_total: int = 0
_callback: Callable[[int, int], None] | None = None


def setup(total: int, callback: Callable[[int, int], None]):
    """初始化求值进度计数器。

    调用方在 evaluate 之前调用。callback(completed, total) 在每次节点
    计算完成时被调用（已持有 _lock，线程安全）。
    """
    global _completed, _total, _callback
    with _lock:
        _completed = 0
        _total = total
        _callback = callback


def teardown():
    """清空进度计数器。evaluate 完成后必须调用。"""
    global _completed, _total, _callback
    with _lock:
        _completed = 0
        _total = 0
        _callback = None


def bump():
    """递增计数器并触发回调。由 FactorExpr.evaluate() 内部调用。"""
    global _completed, _total, _callback
    cb = None
    completed = 0
    total = 0
    with _lock:
        _completed += 1
        completed = _completed
        total = _total
        cb = _callback
    if cb is not None:
        cb(completed, total)


def count_nodes(expr: FactorExpr) -> int:
    """统计表达式树的节点总数（按 structural_key 去重）。"""
    seen: set = set()
    stack = [expr]
    count = 0
    while stack:
        node = stack.pop()
        sk = node._structural_key()
        if sk in seen:
            continue
        seen.add(sk)
        count += 1
        for opnd in reversed(list(getattr(node, 'operands', ()))):
            stack.append(opnd)
    return count
