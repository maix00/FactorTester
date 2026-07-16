from __future__ import annotations

import os
import time


def cpu_bound_success(payload, sink, cancel_event):
    total = int(payload.get("total") or 25000)
    sink.emit_start(total=total, groups=1, phase="cpu")
    acc = 0
    halfway = max(1, total // 2)
    for i in range(total):
        if cancel_event.is_set():
            sink.emit_error("cancelled in worker", cancelled=True)
            return None
        acc = (acc + (i * i)) % 1000003
        if i == halfway:
            sink.emit_progress(i, total, "cpu")
    return {"success": True, "pid": os.getpid(), "acc": acc}


def slow_success(payload, sink, cancel_event):
    duration = float(payload.get("duration") or 0.25)
    sink.emit_start(total=1, groups=1, phase="sleep")
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        if cancel_event.is_set():
            sink.emit_error("cancelled in slow worker", cancelled=True)
            return None
        time.sleep(0.01)
    sink.emit_progress(1, 1, "sleep")
    return {"success": True, "pid": os.getpid(), "slept": duration}


def waits_for_cancel(payload, sink, cancel_event):
    sink.emit_start(total=1, groups=1, phase="cancel_wait")
    deadline = time.monotonic() + float(payload.get("timeout") or 5.0)
    while time.monotonic() < deadline:
        if cancel_event.is_set():
            sink.emit_error("cancelled by parent", cancelled=True)
            return None
        time.sleep(0.01)
    return {"success": True, "pid": os.getpid(), "cancelled": False}


def raises_error(payload, sink, cancel_event):
    sink.emit_start(total=1, groups=1, phase="fail")
    raise RuntimeError(str(payload.get("message") or "process boom"))


def crashes(payload, sink, cancel_event):
    sink.emit_start(total=1, groups=1, phase="crash")
    os._exit(int(payload.get("exitcode") or 7))
