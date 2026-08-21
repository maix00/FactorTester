"""Long-lived isolated execution workers with bounded cache affinity."""

from __future__ import annotations

import gc
import importlib
import hashlib
import multiprocessing
import os
from pathlib import Path
import queue
import resource
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any

from server.jobs.equity_curve_artifact import receipt_bytes
from server.jobs.json_artifact_writer import (
    write_json_artifact,
    write_json_mapping_artifact,
)
from server.jobs.report_outputs import (
    OUTPUT_DEFINITIONS,
    build_report_artifacts,
    bundle_reports,
    default_output_requests,
    normalize_output_requests,
    source_artifacts_for,
)
from server.jobs.scheduling.result_projection import (
    _bounded_summary,
    persisted_result_summary,
)


class WorkerUnavailable(RuntimeError):
    pass


_EXECUTION_PROGRESS_SHARE = 85.0
_REPORT_BUILD_PROGRESS_SHARE = 10.0
_ARTIFACT_PUBLISH_PROGRESS_SHARE = 5.0
_ARTIFACT_PUBLISH_PROGRESS_START = (
    _EXECUTION_PROGRESS_SHARE + _REPORT_BUILD_PROGRESS_SHARE
)
_PROGRESS_PHASE_WEIGHTS = {
    "pre_replay": 5.0,
    "event_replay": 75.0,
    # Native post-replay work owns the first 5%; result derivation and
    # artifact publication continue in this same semantic phase for 15%.
    "post_replay": 20.0,
}
_OUTPUT_PROGRESS_FLOWS = (
    {
        "flow_key": "build_requested_outputs",
        "flow_label": "构建所选结果",
        "display_order": 10_000,
    },
    {
        "flow_key": "publish_artifacts",
        "flow_label": "写入并登记生成物",
        "display_order": 10_001,
    },
)


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
        artifact_job_id: str = "",
        artifact_root: str = "",
        retention_mode: str = "summary",
        output_requests: list[str] | tuple[str, ...] = (),
        control_queue: Any = None,
        cancel_event: Any = None,
    ) -> None:
        self.job_id = str(job_id)
        self.artifact_job_id = str(artifact_job_id or job_id)
        self.output_queue = output_queue
        self.artifact_root = Path(artifact_root) if artifact_root else None
        self.retention_mode = str(retention_mode)
        self.output_requests = tuple(normalize_output_requests(list(output_requests)))
        self._source_artifacts = source_artifacts_for(self.output_requests)
        self._source_payloads: dict[str, Any] = {}
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

    def wants_live_event(self, event: str) -> bool:
        """Return whether constructing a new live payload is useful now."""
        last = self._last_live_emit_at.get(str(event))
        return last is None or time.monotonic() - last >= self._live_event_interval

    def _flush_live_events(self) -> None:
        pending = self._pending_live_events
        self._pending_live_events = {}
        # Activity explains the current work; numeric progress is the final
        # snapshot consumed after reconnect. Preserve both while ensuring the
        # broker's latest_progress points at the measurable event.
        priority = {"activity": 0, "signal_progress": 1, "progress": 2}
        for event, data in sorted(
            pending.items(), key=lambda item: priority.get(item[0], 1),
        ):
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
        declared: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in phases:
            phase = dict(raw)
            key = str(phase.get("key") or phase.get("phase") or "").strip()
            if not key or key in seen:
                continue
            phase["key"] = key
            phase.setdefault("weight", _PROGRESS_PHASE_WEIGHTS.get(key, 1.0))
            declared.append(phase)
            seen.add(key)
        post_replay = next(
            (phase for phase in declared if phase["key"] == "post_replay"),
            None,
        )
        if post_replay is None:
            post_replay = {
                "key": "post_replay",
                "label": "结果整理",
                "weight": _PROGRESS_PHASE_WEIGHTS["post_replay"],
                "flows": [],
            }
            declared.append(post_replay)
        post_replay["weight"] = _PROGRESS_PHASE_WEIGHTS["post_replay"]
        flows = list(post_replay.get("flows") or [])
        flow_keys = {
            str(item.get("flow_key") or item.get("key") or "")
            for item in flows
        }
        flows.extend(
            dict(item) for item in _OUTPUT_PROGRESS_FLOWS
            if item["flow_key"] not in flow_keys
        )
        post_replay["flows"] = flows
        self._emit("activity_manifest", {"phases": declared})

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
        percent_scope = "phase"
        if percent is None:
            percent = 100.0 if total <= 0 else completed / total * 100.0
        else:
            # Native execution percentages describe the complete replay. The
            # worker still has to derive, encode, write, and register requested
            # outputs, so execution owns only the leading progress segment.
            percent = float(percent) * _EXECUTION_PROGRESS_SHARE / 100.0
            percent_scope = "global"
        self._emit_live("signal_progress", {
            "completed": completed,
            "total": total,
            "phase": phase,
            "percent": max(0.0, min(100.0, float(percent))),
            "percent_scope": percent_scope,
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

    def emit_result(self, data: dict[str, Any], *, source: dict[str, Any] | None = None) -> None:
        # Keep the legacy equity report automatic, while allowing a RunSpec to
        # request additional reports without retaining the complete result.
        implicit_default = not self.output_requests
        implicit_ic = implicit_default and any(
            isinstance(item, dict)
            and (
                item.get("ic_series_by_forward_horizon")
                or item.get("ic_series")
            )
            for item in (data.get("factors") or ())
        )
        requested = list(self.output_requests) or (
            default_output_requests(["ic"])
            if implicit_ic else ["equity_curve"]
        )
        merged_source = dict(self._source_payloads)
        merged_source.update(source or {})
        self.emit_activity(
            phase="post_replay",
            phase_label="结果整理",
            flow_key="build_requested_outputs",
            flow_label="构建所选结果",
            message=f"正在派生并编码 {len(requested)} 项所选结果",
        )

        def report_progress(completed: int, total: int, name: str) -> None:
            label = str(OUTPUT_DEFINITIONS.get(name, {}).get("label") or name)
            self.emit_activity(
                phase="post_replay",
                phase_label="结果整理",
                flow_key="build_requested_outputs",
                flow_label="构建所选结果",
                message=f"已构建 {label}",
            )
            percent = (
                _EXECUTION_PROGRESS_SHARE
                + completed / max(1, total) * _REPORT_BUILD_PROGRESS_SHARE
            )
            self.emit_progress(
                completed, max(1, total), "post_replay",
                percent=percent, percent_scope="global",
                message=f"已构建 {completed}/{total} 项结果：{label}",
            )

        reports = build_report_artifacts(
            data,
            source=merged_source,
            requested=requested,
            job_id=self.job_id,
            progress=report_progress,
        )
        has_equity_curve = any(report.name == "equity_curve_report" for report in reports)
        retain_result = self.retention_mode == "full" or "result" in self._source_artifacts
        bundles = bundle_reports(reports)
        publish_total = len(reports) + len(bundles) + int(retain_result)
        self.emit_activity(
            phase="post_replay",
            phase_label="结果整理",
            flow_key="publish_artifacts",
            flow_label="写入并登记生成物",
            message=f"正在写入并登记 {publish_total} 项生成物",
        )
        published = 0
        for report in reports:
            self._write_bytes_artifact(
                report.name,
                report.raw,
                extension=report.extension,
                content_type=report.content_type,
            )
            published += 1
            self.emit_progress(
                published, max(1, publish_total), "post_replay",
                percent=(
                    _ARTIFACT_PUBLISH_PROGRESS_START
                    + published / max(1, publish_total)
                    * _ARTIFACT_PUBLISH_PROGRESS_SHARE
                ),
                percent_scope="global",
                message=f"已登记 {published}/{publish_total} 项生成物",
            )
        for bundle in bundles:
            self._write_bytes_artifact(
                bundle.receipt_name,
                receipt_bytes(bundle.receipt),
                extension="json",
                content_type="application/json",
            )
            published += 1
            self.emit_progress(
                published, max(1, publish_total), "post_replay",
                percent=(
                    _ARTIFACT_PUBLISH_PROGRESS_START
                    + published / max(1, publish_total)
                    * _ARTIFACT_PUBLISH_PROGRESS_SHARE
                ),
                percent_scope="global",
                message=f"已登记 {published}/{publish_total} 项生成物",
            )
        if retain_result:
            self._write_artifact("result", data)
            published += 1
            self.emit_progress(
                published, max(1, publish_total), "post_replay",
                percent=(
                    _ARTIFACT_PUBLISH_PROGRESS_START
                    + published / max(1, publish_total)
                    * _ARTIFACT_PUBLISH_PROGRESS_SHARE
                ),
                percent_scope="global",
                message=f"已登记 {published}/{publish_total} 项生成物",
            )
        if publish_total == 0:
            self.emit_progress(
                1, 1, "post_replay", percent=100.0, percent_scope="global",
                message="无需生成额外文件",
            )
        self._flush_live_events()
        summary = _bounded_summary(data)
        if has_equity_curve:
            summary["equity_curve_artifact_available"] = True
        self._emit("result", summary)

    def emit_plan(self, data: dict[str, Any]) -> None:
        """Return a planning result without invoking execution artifact builders."""
        self._flush_live_events()
        self._emit("result", _bounded_summary(data))

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
        if self.retention_mode == "full" or str(name) in self._source_artifacts:
            if str(name) in self._source_artifacts:
                self._source_payloads[str(name)] = value
            self._write_artifact(str(name), value)

    def emit_core_artifact(self, name: str, value: Any) -> None:
        """Persist a bounded Job result index independent of optional outputs.

        Core artifacts back the standard Job result UI.  They are not an
        opt-in report and must remain available under summary retention, while
        large execution traces continue to obey ``output_requests``.
        """
        self._write_artifact(str(name), value)

    def emit_mapping_artifact(
        self,
        name: str,
        *,
        fields: dict[str, Any],
        mapping_name: str,
        items: Any,
    ) -> None:
        name = str(name)
        if not self.should_retain_artifact(name):
            return
        if name in self._source_artifacts:
            value = {**fields, str(mapping_name): dict(items)}
            self._source_payloads[name] = value
            self._write_artifact(name, value)
            return
        if self.artifact_root is None:
            raise RuntimeError("artifact root is required for full retention")
        safe_name = "".join(
            ch if ch.isalnum() or ch in "-_" else "-"
            for ch in name
        )
        target = self.artifact_root / self.artifact_job_id / f"{safe_name}.json"
        receipt = write_json_mapping_artifact(
            target,
            fields=fields,
            mapping_name=str(mapping_name),
            items=items,
        )
        self._emit("artifact", {
            "name": name,
            "relative_path": f"{self.artifact_job_id}/{target.name}",
            "content_type": "application/json",
            "content_hash": receipt.content_hash,
            "size_bytes": receipt.size_bytes,
        })

    def should_retain_artifact(self, name: str) -> bool:
        return self.retention_mode == "full" or str(name) in self._source_artifacts

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
        safe_name = "".join(
            ch if ch.isalnum() or ch in "-_" else "-"
            for ch in name
        )
        directory = self.artifact_root / self.artifact_job_id
        target = directory / f"{safe_name}.json"
        receipt = write_json_artifact(target, value)
        self._emit("artifact", {
            "name": name,
            "relative_path": f"{self.artifact_job_id}/{target.name}",
            "content_type": "application/json",
            "content_hash": receipt.content_hash,
            "size_bytes": receipt.size_bytes,
        })

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
        directory = self.artifact_root / self.artifact_job_id
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{safe_name}.{extension}"
        staging = directory / f".{safe_name}.{os.getpid()}.tmp"
        staging.write_bytes(raw)
        staging.replace(target)
        self._emit("artifact", {
            "name": name,
            "relative_path": f"{self.artifact_job_id}/{target.name}",
            "content_type": content_type,
            "content_hash": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
        })


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
    recycle_peak_rss_bytes: int,
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
        runner = None
        sink = None
        try:
            runner = _load_runner(str(task["runner_path"]))
            cancel_flag = _CancelFlag(cancel_value)
            sink = _WorkerSink(
                job_id,
                output_queue,
                artifact_job_id=str(task.get("artifact_job_id") or job_id),
                artifact_root=str(task.get("artifact_root") or ""),
                retention_mode=str(task.get("retention_mode") or "summary"),
                output_requests=list(
                    (task.get("payload") or {}).get("output_requests") or ()
                ),
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
            runner = None
            sink = None
            gc.collect()
            peak_rss_bytes = _peak_rss_bytes()
            recycle_requested = bool(
                recycle_peak_rss_bytes > 0
                and peak_rss_bytes >= recycle_peak_rss_bytes
            )
            output_queue.put({
                "type": "task_finished",
                "job_id": job_id,
                "worker_id": worker_id,
                "worker_pid": os.getpid(),
                "cache_keys": list(task.get("cache_keys") or []),
                "terminal_emitted_by_pool": terminal_emitted,
                "peak_rss_bytes": peak_rss_bytes,
                "recycle_requested": recycle_requested,
            })
        if recycle_requested:
            return


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


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
        recycle_peak_rss_bytes: int | None = None,
    ) -> None:
        self.size = max(1, int(size))
        self.cancel_grace_seconds = max(0.0, float(cancel_grace_seconds))
        self.max_cache_keys_per_worker = max(1, int(max_cache_keys_per_worker))
        if recycle_peak_rss_bytes is None:
            recycle_peak_rss_bytes = int(os.environ.get(
                "GTHT_JOB_WORKER_RECYCLE_PEAK_RSS_BYTES",
                str(3 * 1024**3),
            ))
        self.recycle_peak_rss_bytes = max(0, int(recycle_peak_rss_bytes))
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
            args=(
                worker_id,
                task_queue,
                self.output_queue,
                cancel_value,
                self.recycle_peak_rss_bytes,
            ),
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
        artifact_job_id: str = "",
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
                "artifact_job_id": str(artifact_job_id or job_id),
            })
            return worker.process.pid

    def request_cancel(self, job_id: str) -> bool:
        with self._lock:
            worker_id = self._job_to_worker.get(str(job_id))
            if worker_id is None:
                return False
            worker = self._workers[worker_id]
            worker.cancel_value.value = 1
            if worker.cancel_requested_at is None:
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
            if bool(message.get("recycle_requested")):
                self._job_to_worker.pop(job_id, None)
                worker.process.join(timeout=0.5)
                if worker.process.is_alive():
                    worker.process.terminate()
                    worker.process.join(timeout=1.0)
                try:
                    worker.task_queue.close()
                except Exception:
                    pass
                if not self._closed:
                    self._workers[worker_id] = self._spawn(worker_id)
                return
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
