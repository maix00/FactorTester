from __future__ import annotations

import os
import time


def cpu_runner(payload, sink, cancel_event) -> None:
    loops = int(payload.get("loops") or 100_000)
    total = 0
    for value in range(loops):
        total = (total + value * value) % 1_000_003
        if value % 10_000 == 0 and cancel_event.is_set():
            sink.emit_error("cancelled", cancelled=True)
            return
    sink.emit_result({"success": True, "pid": os.getpid(), "value": total})


def blocking_runner(payload, sink, cancel_event) -> None:
    deadline = time.monotonic() + float(payload.get("seconds") or 5.0)
    while time.monotonic() < deadline:
        if cancel_event.is_set():
            sink.emit_error("cancelled", cancelled=True)
            return
        time.sleep(0.01)
    sink.emit_result({"success": True, "pid": os.getpid()})


def uncooperative_runner(payload, sink, cancel_event) -> None:
    time.sleep(float(payload.get("seconds") or 5.0))
    sink.emit_result({"success": True, "pid": os.getpid()})


def crash_runner(payload, sink, cancel_event) -> None:
    os._exit(int(payload.get("exitcode") or 17))
