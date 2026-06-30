"""SSE 进度推送基础设施

为任何需要流式推送进度的端点提供统一的 SSE emitter。
配合 eval_progress 使用可实现节点级进度反馈。

用法：
    from server.services.sse_progress import SSEProgressEmitter

    emitter = SSEProgressEmitter()

    def heavy_work(emitter):
        from server.services.eval_progress import setup, teardown, count_nodes
        total = count_nodes(expr)
        setup(total, lambda c, t: emitter.emit_progress(c, t, 'eval'))
        try:
            # ... 执行计算 ...
            emitter.emit_result({'success': True, 'data': ...})
        except Exception as e:
            emitter.emit_error(str(e))
        finally:
            teardown()

    threading.Thread(target=heavy_work, args=(emitter,), daemon=True).start()
    return emitter.get_response()
"""
from __future__ import annotations

import orjson
import queue
import threading
from typing import Any, Dict, List, Optional

from flask import Response, stream_with_context


class SSEProgressEmitter:
    """SSE 流式进度推送器 — queue + thread + SSE generate 一体化。

    工作线程通过 emit_*() 方法推送事件，主线程调用 get_response() 返回 Flask Response。
    哨兵 None 自动触发流结束。
    """

    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()

    # ── 事件发射（工具线程调用） ──

    def emit_start(self, *, total: int, groups: int, phase: str = "init", phases: Optional[List[dict]] = None, **extra) -> None:
        payload: Dict[str, Any] = {"total": total, "groups": groups, "phase": phase}
        if phases:
            payload["phases"] = phases
        payload.update(extra)
        self._q.put(self._event("start", payload))

    def emit_progress(self, completed: int, total: int, phase: str = "eval", **extra) -> None:
        payload: Dict[str, Any] = {"completed": completed, "total": total, "phase": phase}
        payload.update(extra)
        self._q.put(self._event("progress", payload))

    def emit_activity_manifest(self, phases: List[dict]) -> None:
        self._q.put(self._event("activity_manifest", {"phases": phases}))

    def emit_activity(self, **payload: Any) -> None:
        self._q.put(self._event("activity", payload))

    def emit_signal_progress(self, *, completed: int, total: int, phase: str = "event_replay") -> None:
        percent = 100.0 if total <= 0 else max(0.0, min(100.0, completed / total * 100.0))
        self._q.put(self._event("signal_progress", {
            "completed": completed,
            "total": total,
            "percent": percent,
            "phase": phase,
        }))

    def emit_runtime_info(
        self,
        message: str,
        *,
        level: str = "info",
        code: str = "",
        details: Optional[Dict[str, Any]] = None,
        **extra,
    ) -> None:
        payload: Dict[str, Any] = {"message": message, "level": level, "code": code}
        if details is not None:
            payload["details"] = details
        payload.update(extra)
        self._q.put(self._event("runtime_info", payload))

    def emit_result(self, data: Dict[str, Any]) -> None:
        self._q.put(self._event("result", data))

    def emit_error(self, error: str, traceback: str = "", **extra) -> None:
        payload: Dict[str, Any] = {"success": False, "error": error, "traceback": traceback}
        payload.update(extra)
        self._q.put(self._event("error", payload))

    def close(self) -> None:
        """发送流结束哨兵。工作线程完成后调用。"""
        self._q.put(None)

    # ── Flask Response（主线程调用） ──

    def get_response(self) -> Response:
        """返回 SSE Flask Response。必须在主线程（Flask request context）中调用。"""
        return Response(
            stream_with_context(self._generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # ── 内部方法 ──

    @staticmethod
    def _event(name: str, payload: Dict[str, Any]) -> str:
        return f"event: {name}\ndata: {orjson.dumps(payload, option=orjson.OPT_SERIALIZE_NUMPY).decode()}\n\n"

    def _generate(self):
        while True:
            chunk = self._q.get()
            if chunk is None:
                break
            yield chunk
