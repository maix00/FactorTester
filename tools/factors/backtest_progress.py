"""
统一回测进度注册器 — 独立于 server/HTTP 层，放在 tools/ 供引擎侧直接使用。

一个 tab / 一个回测任务一个实例。

引擎侧调用 emit_*() 方法写入进度；
SSE/HTTP 适配侧通过 register_*() 绑定回调，无需引擎层感知传输细节。

用法：:

  registry = BacktestProgressRegistry()

  # ---- SSE/HTTP 适配侧 ----
  registry.register_before(lambda total, groups, phase, extra: emitter.emit_start(...))
  registry.register_phase(lambda phase, msg, completed, total, extra: emitter.emit_progress(...))
  registry.register_after(lambda success, data: emitter.emit_result(data) if success else emitter.emit_error(...))

  # ---- 引擎侧 ----
  registry.emit_start(total=10, groups=5)
  registry.emit_phase("membership", completed=3, total=10)
  registry.emit_result({"success": True, ...})
  registry.emit_error("something broke")
  registry.cleanup()
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Dict

# 回调签名
BeforeCallback = Callable[[int, int, str, Dict[str, Any]], None]
# before(total, groups, phase, extra)

PhaseCallback = Callable[[str, str, int, int, Dict[str, Any]], None]
# phase(phase_key, message, completed, total, extra)

AfterCallback = Callable[[bool, Dict[str, Any]], None]
# after(success: bool, data: dict)


class BacktestProgressRegistry:
    """每个回测任务（一次 POST 请求）创建一个实例。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._before: BeforeCallback | None = None
        self._phase: PhaseCallback | None = None
        self._after: AfterCallback | None = None
        self._started = False

    # ── SSE/HTTP 适配侧注册回调 ──

    def register_before(self, callback: BeforeCallback) -> None:
        self._before = callback

    def register_phase(self, callback: PhaseCallback) -> None:
        self._phase = callback

    def register_after(self, callback: AfterCallback) -> None:
        self._after = callback

    # ── 引擎侧发射事件 ──

    def emit_start(self, *, total: int, groups: int = 0, phase: str = "init", **extra) -> None:
        self._started = True
        cb = self._before
        if cb is not None:
            try:
                cb(total, groups, phase, extra)
            except Exception:
                pass

    def emit_phase(self, phase: str, *, message: str = "",
                   completed: int = 0, total: int = 0, **extra) -> None:
        cb = self._phase
        if cb is not None:
            try:
                cb(phase, message, completed, total, extra)
            except Exception:
                pass

    def emit_result(self, data: Dict[str, Any]) -> None:
        cb = self._after
        if cb is not None:
            try:
                cb(True, data)
            except Exception:
                pass

    def emit_error(self, error: str, **extra) -> None:
        cb = self._after
        if cb is not None:
            try:
                cb(False, {"error": error, **extra})
            except Exception:
                pass

    def cleanup(self) -> None:
        with self._lock:
            self._before = None
            self._phase = None
            self._after = None
