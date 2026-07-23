"""Long-lived isolated execution workers with bounded cache affinity."""

from __future__ import annotations

import importlib
import hashlib
import multiprocessing
import os
from pathlib import Path
import queue
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any

import orjson

from server.jobs.equity_curve_artifact import (
    build_equity_curve_artifact,
    receipt_bytes,
)


class WorkerUnavailable(RuntimeError):
    pass


class _CancelFlag:
    def __init__(self, value: Any) -> None:
        self._value = value

    def is_set(self) -> bool:
        return bool(self._value.value)


class _WorkerSink:
    def __init__(
        self,
        job_id: str,
        output_queue: Any,
        *,
        artifact_root: str = "",
        retention_mode: str = "summary",
        control_queue: Any = None,
        cancel_event: Any = None,
    ) -> None:
        self.job_id = str(job_id)
        self.output_queue = output_queue
        self.artifact_root = Path(artifact_root) if artifact_root else None
        self.retention_mode = str(retention_mode)
        self.control_queue = control_queue
        self.cancel_event = cancel_event
        self._live_event_interval = 0.5
        self._last_live_emit_at: dict[str, float] = {}
        self._pending_live_events: dict[str, dict[str, Any]] = {}

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        self.output_queue.put({
            "type": "event",
            "job_id": self.job_id,
            "event": str(event),
            "data": dict(data),
            "worker_pid": os.getpid(),
        })

    def _emit_live(self, event: str, data: dict[str, Any]) -> None:
        now = time.monotonic()
        last = self._last_live_emit_at.get(event)
        if last is not None and now - last < self._live_event_interval:
            self._pending_live_events[event] = dict(data)
            return
        self._pending_live_events.pop(event, None)
        self._last_live_emit_at[event] = now
        self._emit(event, data)

    def _flush_live_events(self) -> None:
        pending = self._pending_live_events
        self._pending_live_events = {}
        for event, data in pending.items():
            self._last_live_emit_at[event] = time.monotonic()
            self._emit(event, data)

    def emit_start(self, *, total: int, groups: int, phase: str = "init", phases=None, **extra) -> None:
        data: dict[str, Any] = {"total": total, "groups": groups, "phase": phase}
        if phases:
            data["phases"] = phases
        data.update(extra)
        self._emit("start", data)

    def emit_progress(self, completed: int, total: int, phase: str = "eval", **extra) -> None:
        self._emit_live("progress", {
            "completed": completed,
            "total": total,
            "phase": phase,
            **extra,
        })

    def emit_activity_manifest(self, phases: list[dict[str, Any]]) -> None:
        self._emit("activity_manifest", {"phases": phases})

    def emit_activity(self, **payload: Any) -> None:
        self._emit_live("activity", payload)

    def emit_signal_progress(
        self,
        *,
        completed: int,
        total: int,
        phase: str = "event_replay",
        percent: float | None = None,
    ) -> None:
        if percent is None:
            percent = 100.0 if total <= 0 else completed / total * 100.0
        self._emit_live("signal_progress", {
            "completed": completed,
            "total": total,
            "phase": phase,
            "percent": max(0.0, min(100.0, float(percent))),
        })

    def emit_runtime_info(
        self,
        message: str,
        *,
        level: str = "info",
        code: str = "",
        details: dict[str, Any] | None = None,
        **extra,
    ) -> None:
        data: dict[str, Any] = {
            "message": message,
            "level": level,
            "code": code,
            **extra,
        }
        if details is not None:
            data["details"] = details
        self._emit("runtime_info", data)

    def emit_result(self, data: dict[str, Any]) -> None:
        curve = build_equity_curve_artifact(data)
        if curve is not None:
            image, receipt = curve
            self._write_bytes_artifact(
                "equity_curve_report",
                image,
                extension="svg",
                content_type="image/svg+xml",
            )
            self._write_bytes_artifact(
                "equity_curve_receipt",
                receipt_bytes(receipt),
                extension="json",
                content_type="application/json",
            )
        if self.retention_mode == "full":
            self._write_artifact("result", data)
        self._flush_live_events()
        summary = _bounded_summary(data)
        if curve is not None:
            summary["equity_curve_artifact_available"] = True
        self._emit("result", summary)

    def emit_error(self, error: str, traceback: str = "", **extra) -> None:
        self._flush_live_events()
        self._emit("error", {
            "success": False,
            "error": error,
            "traceback": traceback,
            **extra,
        })

    def emit_step(self, step_info: dict[str, Any]) -> None:
        self._emit("step", dict(step_info))

    def emit_artifact(self, name: str, value: Any) -> None:
        if self.retention_mode == "full":
            self._write_artifact(str(name), value)

    def emit_pause(self, checkpoint: dict[str, Any]) -> dict[str, Any]:
        self._flush_live_events()
        self._emit("paused", {"checkpoint": dict(checkpoint)})
        if self.control_queue is None:
            return {"action": "cancel"}
        while True:
            if self.cancel_event is not None and self.cancel_event.is_set():
                return {"action": "cancel"}
            try:
                command = self.control_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if isinstance(command, dict) and command.get("type") == "step_control":
                return dict(command.get("command") or {})

    def _write_artifact(self, name: str, value: Any) -> None:
        if self.artifact_root is None:
            raise RuntimeError("artifact root is required for full retention")
        self._write_bytes_artifact(
            name,
            _json_bytes(value),
            extension="json",
            content_type="application/json",
        )

    def _write_bytes_artifact(
        self,
        name: str,
        raw: bytes,
        *,
        extension: str,
        content_type: str,
    ) -> None:
        if self.artifact_root is None:
            raise RuntimeError("artifact root is required")
        safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name)
        directory = self.artifact_root / self.job_id
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{safe_name}.{extension}"
        staging = directory / f".{safe_name}.{os.getpid()}.tmp"
        staging.write_bytes(raw)
        staging.replace(target)
        self._emit("artifact", {
            "name": name,
            "relative_path": f"{self.job_id}/{target.name}",
            "content_type": content_type,
            "content_hash": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
        })


def _bounded_summary(data: dict[str, Any], *, max_bytes: int = 512 * 1024) -> dict[str, Any]:
    raw = _json_bytes(data)
    if len(raw) <= max_bytes:
        return dict(data)
    summary: dict[str, Any] = {
        "success": bool(data.get("success", True)),
        "summary_truncated": True,
        "full_result_bytes": len(raw),
    }
    groups = data.get("groups")
    group_reserve = min(128 * 1024, max_bytes // 2) if isinstance(groups, list) else 0
    non_group_limit = max_bytes - group_reserve
    for key, value in data.items():
        if key in {"success", "groups", "equity_curve", "curves", "details", "engine_result"}:
            continue
        candidate = {**summary, key: value}
        if len(_json_bytes(candidate)) <= non_group_limit:
            summary[key] = value
    if isinstance(groups, list):
        candidate = {**summary, "groups": groups}
        if len(_json_bytes(candidate)) <= max_bytes:
            summary["groups"] = groups
        else:
            chart_groups, downsampled = _bounded_chart_groups(
                groups,
                byte_budget=max_bytes - len(_json_bytes(summary)),
            )
            summary["groups"] = chart_groups
            summary["groups_chart_only"] = True
            summary["equity_curve_downsampled"] = downsampled
    return summary


def persisted_result_summary(
    data: dict[str, Any],
    *,
    max_bytes: int = 64 * 1024,
) -> dict[str, Any]:
    """Project terminal facts without persisting chart point sequences.

    The live broker may briefly carry the bounded chart series so the current
    browser session remains interactive.  Durable history uses the immutable
    SVG artifact instead; keeping the same points in SQLite would duplicate a
    quota-bearing report projection on every status/detail read.
    """
    projected: dict[str, Any] = {
        "success": bool(data.get("success", True)),
        "equity_curve_points_persisted": False,
    }
    if data.get("equity_curve_artifact_available") is True:
        projected.update({
            "equity_curve_artifact_available": True,
            "equity_curve_artifact": "equity_curve_report",
            "equity_curve_receipt_artifact": "equity_curve_receipt",
        })
    excluded = {
        "groups", "equity_curve", "curves", "details", "engine_result",
    }
    for key, value in data.items():
        if key in excluded or key == "success":
            continue
        candidate = {**projected, key: value}
        if len(_json_bytes(candidate)) <= max_bytes:
            projected[key] = value

    groups = data.get("groups")
    if isinstance(groups, list):
        compact_groups = [_persisted_group(value) for value in groups]
        candidate = {**projected, "groups": compact_groups}
        if len(_json_bytes(candidate)) <= max_bytes:
            projected["groups"] = compact_groups
        else:
            projected["group_count"] = len(compact_groups)
            projected["group_summaries_omitted"] = True
    return projected


def _persisted_group(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    curve_keys = {
        "timestamps", "total_equity", "gross_returns", "net_returns",
        "equity_curve", "curves", "daily_returns", "period_returns",
        "pre_rebalance_total_equity", "post_rebalance_total_equity",
    }
    compact: dict[str, Any] = {}
    for key, item in value.items():
        if key in curve_keys:
            continue
        # A group summary should contain identifiers and statistical facts, not
        # another opaque payload large enough to become an accidental artifact.
        if len(_json_bytes(item)) <= 16 * 1024:
            compact[key] = item
    compact["equity_curve_points_persisted"] = False
    return compact


def _bounded_chart_groups(
    groups: list[Any],
    *,
    byte_budget: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Keep the Web chart contract even when the full job result is truncated."""
    scalar_keys = (
        "key", "name", "group_id", "group_index", "product_path_selection_id",
        "factor_alias", "engine", "allocation_policy", "rebalance_trigger",
        "position_policy", "target_trace_available", "snapshot_available",
        "is_ls", "ls_info",
    )
    stride = 1
    while True:
        result = []
        for value in groups:
            group = value if isinstance(value, dict) else {}
            compact = {key: group[key] for key in scalar_keys if key in group}
            timestamps = list(group.get("timestamps") or [])
            equity = list(group.get("total_equity") or [])
            gross_returns = list(group.get("gross_returns") or [])
            point_count = min(len(timestamps), len(equity))
            indices = list(range(0, point_count, stride))
            if point_count and (not indices or indices[-1] != point_count - 1):
                indices.append(point_count - 1)
            compact["timestamps"] = [timestamps[index] for index in indices]
            compact["total_equity"] = [equity[index] for index in indices]
            if len(gross_returns) >= point_count:
                compact["gross_returns"] = [gross_returns[index] for index in indices]
            compact["equity_curve_original_points"] = point_count
            result.append(compact)
        if len(_json_bytes(result)) <= max(0, byte_budget) or stride >= 1024:
            return result, stride > 1
        stride *= 2


def _json_bytes(value: Any) -> bytes:
    return orjson.dumps(
        value,
        option=orjson.OPT_SERIALIZE_NUMPY,
        default=str,
    )


def _load_runner(path: str):
    module_name, separator, attr = str(path).partition(":")
    if not separator or not module_name or not attr:
        raise ValueError("runner path must use module:function")
    runner = getattr(importlib.import_module(module_name), attr)
    if not callable(runner):
        raise TypeError(f"runner is not callable: {path}")
    return runner


def _worker_entry(
    worker_id: int,
    task_queue: Any,
    output_queue: Any,
    cancel_value: Any,
) -> None:
    from server.jobs.worker_runtime import initialize_worker_runtime

    initialize_worker_runtime()
    try:
        from tools.data.cache.IdleResourceManager import IdleResourceManager

        IdleResourceManager.get_instance().start(idle_timeout=300, scan_interval=30)
    except Exception:
        pass
    output_queue.put({
        "type": "worker_ready",
        "worker_id": worker_id,
        "worker_pid": os.getpid(),
    })
    while True:
        task = task_queue.get()
        if task is None:
            return
        cancel_value.value = 0
        job_id = str(task["job_id"])
        output_queue.put({
            "type": "task_started",
            "job_id": job_id,
            "worker_id": worker_id,
            "worker_pid": os.getpid(),
        })
        terminal_emitted = False
        try:
            runner = _load_runner(str(task["runner_path"]))
            cancel_flag = _CancelFlag(cancel_value)
            sink = _WorkerSink(
                job_id,
                output_queue,
                artifact_root=str(task.get("artifact_root") or ""),
                retention_mode=str(task.get("retention_mode") or "summary"),
                control_queue=task_queue,
                cancel_event=cancel_flag,
            )
            runner(dict(task["payload"]), sink, cancel_flag)
        except BaseException as exc:
            terminal_emitted = True
            output_queue.put({
                "type": "event",
                "job_id": job_id,
                "event": "error",
                "data": {
                    "success": False,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
                "worker_pid": os.getpid(),
            })
        finally:
            output_queue.put({
                "type": "task_finished",
                "job_id": job_id,
                "worker_id": worker_id,
                "worker_pid": os.getpid(),
                "cache_keys": list(task.get("cache_keys") or []),
                "terminal_emitted_by_pool": terminal_emitted,
            })


@dataclass
class _Worker:
    worker_id: int
    task_queue: Any
    output_queue: Any
    cancel_value: Any
    process: Any
    job_id: str = ""
    cache_keys: set[str] = field(default_factory=set)
    cache_key_order: list[str] = field(default_factory=list)
    cancel_requested_at: float | None = None


class LongLivedWorkerPool:
    """Own persistent child processes and select idle workers by cache affinity."""

    def __init__(
        self,
        *,
        size: int,
        cancel_grace_seconds: float = 2.0,
        start_method: str = "spawn",
        max_cache_keys_per_worker: int = 128,
    ) -> None:
        self.size = max(1, int(size))
        self.cancel_grace_seconds = max(0.0, float(cancel_grace_seconds))
        self.max_cache_keys_per_worker = max(1, int(max_cache_keys_per_worker))
        self.context = multiprocessing.get_context(start_method)
        self.output_queue = self.context.Queue()
        self._workers: dict[int, _Worker] = {}
        self._job_to_worker: dict[str, int] = {}
        self._lock = threading.RLock()
        self._closed = False
        for worker_id in range(self.size):
            self._workers[worker_id] = self._spawn(worker_id)

    def _spawn(self, worker_id: int) -> _Worker:
        task_queue = self.context.Queue()
        cancel_value = self.context.Value("b", 0)
        process = self.context.Process(
            target=_worker_entry,
            args=(worker_id, task_queue, self.output_queue, cancel_value),
            daemon=True,
            name=f"research-worker-{worker_id}",
        )
        process.start()
        return _Worker(worker_id, task_queue, self.output_queue, cancel_value, process)

    def submit(
        self,
        *,
        job_id: str,
        runner_path: str,
        payload: dict[str, Any],
        cache_keys: list[str] | tuple[str, ...] = (),
        pinned: bool = False,
        artifact_root: str = "",
        retention_mode: str = "summary",
    ) -> int:
        with self._lock:
            if self._closed:
                raise WorkerUnavailable("worker pool is closed")
            self._reconcile_locked()
            idle = [worker for worker in self._workers.values() if not worker.job_id]
            if not idle:
                raise WorkerUnavailable("no idle execution worker")
            requested = set(str(key) for key in cache_keys)
            if pinned:
                worker = min(idle, key=lambda item: item.worker_id)
            else:
                worker = max(
                    idle,
                    key=lambda item: (
                        len(item.cache_keys & requested),
                        -item.worker_id,
                    ),
                )
            worker.job_id = str(job_id)
            worker.cancel_requested_at = None
            self._job_to_worker[str(job_id)] = worker.worker_id
            worker.task_queue.put({
                "job_id": str(job_id),
                "runner_path": str(runner_path),
                "payload": dict(payload),
                "cache_keys": sorted(requested),
                "artifact_root": str(artifact_root),
                "retention_mode": str(retention_mode),
            })
            return worker.process.pid

    def request_cancel(self, job_id: str) -> bool:
        with self._lock:
            worker_id = self._job_to_worker.get(str(job_id))
            if worker_id is None:
                return False
            worker = self._workers[worker_id]
            worker.cancel_value.value = 1
            worker.cancel_requested_at = time.monotonic()
            return True

    def resume_step(self, job_id: str, command: dict[str, Any]) -> bool:
        with self._lock:
            worker_id = self._job_to_worker.get(str(job_id))
            if worker_id is None:
                return False
            worker = self._workers[worker_id]
            worker.task_queue.put({"type": "step_control", "command": dict(command)})
            return True

    def poll(
        self,
        *,
        timeout: float = 0.0,
        max_messages: int = 1000,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        deadline = time.monotonic() + max(0.0, float(timeout))
        limit = max(1, int(max_messages))
        while len(messages) < limit:
            try:
                if timeout > 0 and not messages:
                    message = self.output_queue.get(
                        timeout=max(0.0, deadline - time.monotonic())
                    )
                else:
                    message = self.output_queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(message, dict):
                messages.append(message)
                self._apply_message(message)
        with self._lock:
            messages.extend(self._reconcile_locked())
        return messages

    def _apply_message(self, message: dict[str, Any]) -> None:
        if message.get("type") != "task_finished":
            return
        worker_id = int(message["worker_id"])
        with self._lock:
            worker = self._workers.get(worker_id)
            if worker is None:
                return
            job_id = str(message.get("job_id") or "")
            for key in (str(value) for value in message.get("cache_keys") or []):
                if key in worker.cache_key_order:
                    worker.cache_key_order.remove(key)
                worker.cache_key_order.append(key)
            if len(worker.cache_key_order) > self.max_cache_keys_per_worker:
                del worker.cache_key_order[:-self.max_cache_keys_per_worker]
            worker.cache_keys = set(worker.cache_key_order)
            worker.job_id = ""
            worker.cancel_requested_at = None
            self._job_to_worker.pop(job_id, None)

    def _reconcile_locked(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        now = time.monotonic()
        for worker_id, worker in list(self._workers.items()):
            forced = (
                worker.job_id
                and worker.cancel_requested_at is not None
                and now - worker.cancel_requested_at >= self.cancel_grace_seconds
            )
            crashed = not worker.process.is_alive()
            if not forced and not crashed:
                continue
            job_id = worker.job_id
            exitcode = worker.process.exitcode
            if forced and worker.process.is_alive():
                worker.process.terminate()
                worker.process.join(timeout=1.0)
                exitcode = worker.process.exitcode
            elif crashed:
                worker.process.join(timeout=0.1)
            try:
                worker.task_queue.close()
            except Exception:
                pass
            self._job_to_worker.pop(job_id, None)
            if job_id:
                messages.append({
                    "type": "worker_terminated" if forced else "worker_crashed",
                    "job_id": job_id,
                    "worker_id": worker_id,
                    "worker_pid": worker.process.pid,
                    "worker_exitcode": exitcode,
                })
            if not self._closed:
                self._workers[worker_id] = self._spawn(worker_id)
        return messages

    def worker_snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            self._reconcile_locked()
            return [
                {
                    "worker_id": worker.worker_id,
                    "pid": worker.process.pid,
                    "alive": worker.process.is_alive(),
                    "job_id": worker.job_id,
                    "cache_keys": sorted(worker.cache_keys),
                }
                for worker in sorted(
                    self._workers.values(), key=lambda item: item.worker_id
                )
            ]

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for worker in self._workers.values():
                if worker.process.is_alive():
                    worker.task_queue.put(None)
            for worker in self._workers.values():
                worker.process.join(timeout=2.0)
                if worker.process.is_alive():
                    worker.process.terminate()
                    worker.process.join(timeout=1.0)
                try:
                    worker.task_queue.close()
                except Exception:
                    pass
            self._workers.clear()
            self._job_to_worker.clear()
            try:
                self.output_queue.close()
            except Exception:
                pass

    def __enter__(self) -> "LongLivedWorkerPool":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
