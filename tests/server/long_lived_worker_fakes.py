from __future__ import annotations

import os
import time


class StringIdentifiedValue:
    def __str__(self) -> str:
        return "factor-alias"


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


def cancel_result_race_runner(payload, sink, cancel_event) -> None:
    deadline = time.monotonic() + float(payload.get("seconds") or 5.0)
    while time.monotonic() < deadline and not cancel_event.is_set():
        time.sleep(0.005)
    sink.emit_result({"success": True, "pid": os.getpid()})


def crash_runner(payload, sink, cancel_event) -> None:
    os._exit(int(payload.get("exitcode") or 17))


def planned_cpu_runner(payload, sink, cancel_event) -> None:
    if not isinstance(payload.get("execution_plan"), dict):
        raise ValueError("execution plan missing")
    sink.emit_progress(1, 2, phase="compute")
    cpu_runner(payload, sink, cancel_event)


def progress_flood_runner(payload, sink, cancel_event) -> None:
    count = int(payload.get("count") or 10_000)
    for index in range(count):
        sink.emit_activity(phase="event_replay", message=f"flow-{index}")
        sink.emit_progress(index + 1, count, phase="event_replay")
        sink.emit_signal_progress(
            completed=index + 1,
            total=count,
            phase="event_replay",
        )
    sink.emit_result({"success": True, "pid": os.getpid(), "count": count})


def product_runtime_probe(payload, sink, cancel_event) -> None:
    from tools.products import product_path_selection

    sink.emit_result({
        "success": product_path_selection._product_resolver is not None,
        "pid": os.getpid(),
    })


def artifact_runner(payload, sink, cancel_event) -> None:
    size = int(payload.get("size") or 2048)
    sink.emit_artifact("details", {"values": list(range(size))})
    sink.emit_result({
        "success": True,
        "pid": os.getpid(),
        "annual_return": 0.12,
        "equity_curve": list(range(size)),
    })


def supplemental_artifact_runner(payload, sink, cancel_event) -> None:
    sink.emit_core_artifact("derived-analysis", {"value": 42})
    sink.emit_result({"success": True, "artifact": "derived-analysis"})


def domain_object_artifact_runner(payload, sink, cancel_event) -> None:
    sink.emit_artifact("domain", {"factor": StringIdentifiedValue()})
    sink.emit_result({"success": True, "pid": os.getpid()})


def pausing_runner(payload, sink, cancel_event) -> None:
    seen = []
    for index in range(3):
        seen.append(index)
        sink.emit_step({"flow_index": index, "pid": os.getpid()})
        command = sink.emit_pause({"flow_index": index, "pid": os.getpid()})
        if command.get("action") == "cancel" or cancel_event.is_set():
            sink.emit_error("cancelled", cancelled=True)
            return
        if command.get("action") == "end":
            break
    sink.emit_result({"success": True, "pid": os.getpid(), "seen": seen})
