"""Durable async research job execution and event delivery.

The registry owns the user-visible lifecycle for long-running FactorTester
tasks. It exposes one API/SSE contract with two execution boundaries:

* ``submit`` runs compatibility targets in the current Flask process. Use this
  for existing page-bound code that closes over Flask request state, page
  runtime objects, FactorTester instances, or other non-serializable objects.
* ``submit_process`` runs importable, payload-serializable runners in a child
  process. This is the CPU-bound boundary; callers must pass only serializable
  data and an import path such as ``"pkg.module:function"``.

SQLite is canonical for metadata, cancellation, events, results, and global
process slots. The in-memory registry only owns live process handles and SSE
fanout for jobs dispatched by the current Flask worker.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
import hashlib
import importlib
import multiprocessing
import os
import pickle
import queue
import copy
import threading
import time
import traceback as traceback_module
import uuid
from typing import Any, Callable, Iterable

import orjson
from flask import Response, stream_with_context

from server.services import test_job_store


TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "expired", "paused"}
_MAX_EVENTS = int(os.environ.get("GTHT_TEST_JOB_MAX_EVENTS", "2000"))
_MAX_WORKERS = max(1, int(os.environ.get("GTHT_TEST_JOB_WORKERS", "2")))
_MAX_PROCESS_WORKERS = max(1, int(os.environ.get("GTHT_TEST_JOB_PROCESS_WORKERS", "2")))
_PROCESS_CANCEL_GRACE_SECONDS = max(0.1, float(os.environ.get("GTHT_TEST_JOB_PROCESS_CANCEL_GRACE_SECONDS", "1.0")))
_JOB_TTL_SECONDS = max(60, int(os.environ.get("GTHT_TEST_JOB_TTL_SECONDS", "86400")))
_EXECUTOR = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="test-job")
_PROCESS_CONTEXT = multiprocessing.get_context(os.environ.get("GTHT_TEST_JOB_PROCESS_START_METHOD", "spawn"))
_SSE_GAP_EVENT = "reset"


class JobConflictError(ValueError):
    def __init__(self, message: str, *, job_id: str) -> None:
        super().__init__(message)
        self.job_id = job_id


class EventGapError(ValueError):
    def __init__(self, message: str, *, oldest_seq: int, requested_seq: int) -> None:
        super().__init__(message)
        self.oldest_seq = oldest_seq
        self.requested_seq = requested_seq


@dataclass(frozen=True, slots=True)
class TestJobEvent:
    seq: int
    event: str
    data: dict[str, Any]
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "event": self.event,
            "data": dict(self.data),
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class TestJob:
    job_id: str
    kind: str
    run_token: str
    run_id: str
    workspace_id: str
    page_uuid: str
    view_uuid: str
    lifecycle_policy: str
    retry_of: str
    attempt: int
    owner: str
    request_digest: str
    request_snapshot: dict[str, Any]
    request_snapshot_bytes: bytes
    cancel_event: threading.Event
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    checkpoint: dict[str, Any] | None = None
    cancel_requested: bool = False
    cancel_reason: str = ""
    future: Future | None = None
    execution_mode: str = "thread"
    runner_path: str | None = None
    worker_pid: int | None = None
    worker_exitcode: int | None = None
    dispatcher_pid: int | None = None
    process_cancel_event: Any | None = None
    process: Any | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)
    _seq: int = 0
    _events: list[TestJobEvent] = field(default_factory=list)
    _closed: bool = False
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _condition: threading.Condition = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_condition", threading.Condition(self._lock))

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def start(self) -> None:
        with self._condition:
            if self.status == "queued":
                self.status = "running"
                self.started_at = time.time()
                self._condition.notify_all()
        test_job_store.update_job_record(self)

    def emit(self, event: str, data: dict[str, Any]) -> TestJobEvent:
        with self._condition:
            self._seq += 1
            item = TestJobEvent(
                seq=self._seq,
                event=str(event),
                data=dict(data),
                created_at=time.time(),
            )
            self._events.append(item)
            if len(self._events) > _MAX_EVENTS:
                del self._events[: len(self._events) - _MAX_EVENTS]
            self._condition.notify_all()
            test_job_store.record_event(self, item)
            return item

    def succeed(self, result: dict[str, Any]) -> None:
        with self._condition:
            self.result = dict(result)
            self.error = None
            self.status = "succeeded"
            self.finished_at = time.time()
            self._condition.notify_all()
        test_job_store.update_job_record(self)

    def fail(self, error: dict[str, Any], *, cancelled: bool = False) -> None:
        with self._condition:
            self.error = dict(error)
            self.cancel_reason = str(self.error.get("cancel_reason") or self.cancel_reason or "")
            self.status = "cancelled" if cancelled else "failed"
            self.finished_at = time.time()
            self._condition.notify_all()
        test_job_store.update_job_record(self, cancel_reason=self.cancel_reason)

    def pause(self, checkpoint: dict[str, Any]) -> None:
        with self._condition:
            self.checkpoint = dict(checkpoint)
            self.status = "paused"
            self.finished_at = time.time()
            self._condition.notify_all()
        test_job_store.update_job_record(self)

    def request_cancel(self, *, reason: str = "") -> bool:
        with self._condition:
            if self.status in TERMINAL_STATUSES and self.status != "paused":
                return False
            self.cancel_requested = True
            self.cancel_reason = str(reason or self.cancel_reason or "explicit_cancel")
            self.cancel_event.set()
            if self.process_cancel_event is not None:
                self.process_cancel_event.set()
            if self.status in {"queued", "paused"}:
                self.fail(
                    {
                        "success": False,
                        "error": "test job cancelled before start",
                        "cancelled": True,
                        "cancel_reason": self.cancel_reason,
                    },
                    cancelled=True,
                )
                self.close()
            else:
                self._condition.notify_all()
                test_job_store.update_job_record(self, cancel_reason=self.cancel_reason)
            return True

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def events_after(self, seq: int = 0) -> list[TestJobEvent]:
        with self._lock:
            if self._events and seq > 0 and seq < self._events[0].seq - 1:
                raise EventGapError(
                    "requested event cursor is no longer available",
                    oldest_seq=self._events[0].seq,
                    requested_seq=seq,
                )
            return [event for event in self._events if event.seq > seq]

    def wait_for_events(self, seq: int, timeout: float = 15.0) -> list[TestJobEvent]:
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                if self._events and seq > 0 and seq < self._events[0].seq - 1:
                    raise EventGapError(
                        "requested event cursor is no longer available",
                        oldest_seq=self._events[0].seq,
                        requested_seq=seq,
                    )
                events = [event for event in self._events if event.seq > seq]
                if events or self._closed:
                    return events
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._condition.wait(timeout=min(remaining, 1.0))

    def summary(self) -> dict[str, Any]:
        with self._lock:
            latest_event = self._events[-1].to_dict() if self._events else None
            latest_progress = next(
                (event.to_dict() for event in reversed(self._events) if event.event == "progress"),
                None,
            )
            manifest = next(
                (event.to_dict() for event in reversed(self._events) if event.event == "activity_manifest"),
                None,
            )
            return {
                "job_id": self.job_id,
                "kind": self.kind,
                "run_token": self.run_token,
                "run_id": self.run_id,
                "workspace_id": self.workspace_id,
                "page_uuid": self.page_uuid,
                "initiator_page_uuid": self.page_uuid,
                "view_uuid": self.view_uuid,
                "lifecycle_policy": self.lifecycle_policy,
                "retry_of": self.retry_of,
                "attempt": self.attempt,
                "status": self.status,
                "cancel_reason": self.cancel_reason,
                "cancel_requested": self.cancel_requested,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "request_digest": self.request_digest,
                "snapshot_bytes": len(self.request_snapshot_bytes),
                "execution_mode": self.execution_mode,
                "runner_path": self.runner_path,
                "worker_pid": self.worker_pid,
                "worker_exitcode": self.worker_exitcode,
                "event_count": self._seq,
                "latest_event": latest_event,
                "latest_progress": latest_progress,
                "manifest": manifest,
                "has_result": self.result is not None,
                "has_error": self.error is not None,
                "checkpoint": copy.deepcopy(self.checkpoint),
            }


class TestJobSink:
    """ProgressSink-compatible adapter that records events on a TestJob."""

    def __init__(self, job: TestJob) -> None:
        self.job = job

    def emit_start(self, *, total: int, groups: int, phase: str = "init", phases=None, **extra) -> None:
        payload: dict[str, Any] = {"total": total, "groups": groups, "phase": phase}
        if phases:
            payload["phases"] = phases
        payload.update(extra)
        self.job.emit("start", payload)

    def emit_progress(self, completed: int, total: int, phase: str = "eval", **extra) -> None:
        payload: dict[str, Any] = {"completed": completed, "total": total, "phase": phase}
        payload.update(extra)
        self.job.emit("progress", payload)

    def emit_activity_manifest(self, phases: list[dict[str, Any]]) -> None:
        self.job.emit("activity_manifest", {"phases": phases})

    def emit_activity(self, **payload: Any) -> None:
        self.job.emit("activity", payload)

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
        percent = max(0.0, min(100.0, float(percent)))
        self.job.emit("signal_progress", {
            "completed": completed,
            "total": total,
            "percent": percent,
            "phase": phase,
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
        payload: dict[str, Any] = {"message": message, "level": level, "code": code}
        if details is not None:
            payload["details"] = details
        payload.update(extra)
        self.job.emit("runtime_info", payload)

    def emit_result(self, data: dict[str, Any]) -> None:
        payload = dict(data)
        payload.setdefault("job_id", self.job.job_id)
        payload.setdefault("run_id", self.job.run_token)
        payload.setdefault("execution_mode", self.job.execution_mode)
        self.job.succeed(payload)
        self.job.emit("result", payload)

    def emit_error(self, error: str, traceback: str = "", **extra) -> None:
        payload: dict[str, Any] = {"success": False, "error": error, "traceback": traceback}
        payload.update(extra)
        cancelled = bool(payload.get("cancelled"))
        self.job.fail(payload, cancelled=cancelled)
        self.job.emit("error", payload)

    def emit_step(self, step_info: dict[str, Any]) -> None:
        self.job.emit("step", step_info)

    def emit_artifact(self, name: str, value: Any) -> None:
        store_artifact(self.job, name, value)
        self.job.emit("artifact", {"name": str(name)})

    def emit_pause(self, checkpoint: dict[str, Any]) -> None:
        store_artifact(self.job, "step_checkpoint", checkpoint)
        self.job.pause(checkpoint)
        self.job.emit("paused", {"checkpoint": checkpoint})

    def close(self) -> None:
        self.job.close()

    def get_response(self) -> Response:
        return stream_response(self.job)


class ProcessJobSink:
    """Progress sink used inside child worker processes.

    It deliberately has no access to the parent ``TestJob`` object. All state
    changes are serialized as queue messages and applied by the parent process.
    """

    def __init__(self, event_queue: Any) -> None:
        self._queue = event_queue
        self._terminal_emitted = False

    @property
    def terminal_emitted(self) -> bool:
        return self._terminal_emitted

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        self._queue.put({"event": str(event), "data": dict(data)})

    def emit_start(self, *, total: int, groups: int, phase: str = "init", phases=None, **extra) -> None:
        payload: dict[str, Any] = {"total": total, "groups": groups, "phase": phase}
        if phases:
            payload["phases"] = phases
        payload.update(extra)
        self._emit("start", payload)

    def emit_progress(self, completed: int, total: int, phase: str = "eval", **extra) -> None:
        payload: dict[str, Any] = {"completed": completed, "total": total, "phase": phase}
        payload.update(extra)
        self._emit("progress", payload)

    def emit_activity_manifest(self, phases: list[dict[str, Any]]) -> None:
        self._emit("activity_manifest", {"phases": phases})

    def emit_activity(self, **payload: Any) -> None:
        self._emit("activity", payload)

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
        percent = max(0.0, min(100.0, float(percent)))
        self._emit("signal_progress", {
            "completed": completed,
            "total": total,
            "percent": percent,
            "phase": phase,
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
        payload: dict[str, Any] = {"message": message, "level": level, "code": code}
        if details is not None:
            payload["details"] = details
        payload.update(extra)
        self._emit("runtime_info", payload)

    def emit_result(self, data: dict[str, Any]) -> None:
        self._terminal_emitted = True
        self._emit("result", dict(data))

    def emit_error(self, error: str, traceback: str = "", **extra) -> None:
        payload: dict[str, Any] = {"success": False, "error": error, "traceback": traceback}
        payload.update(extra)
        self._terminal_emitted = True
        self._emit("error", payload)

    def emit_step(self, step_info: dict[str, Any]) -> None:
        self._emit("step", step_info)

    def emit_artifact(self, name: str, value: Any) -> None:
        self._emit("artifact", {"name": str(name), "value": value})

    def emit_pause(self, checkpoint: dict[str, Any]) -> None:
        self._terminal_emitted = True
        self._emit("paused", {"checkpoint": dict(checkpoint)})


def _load_runner(runner_path: str) -> Callable[[dict[str, Any], ProcessJobSink, Any], dict[str, Any] | None]:
    module_name, sep, attr = str(runner_path).partition(":")
    if not sep or not module_name or not attr:
        raise ValueError("runner_path must be 'module:function'")
    target: Any = importlib.import_module(module_name)
    for part in attr.split("."):
        target = getattr(target, part)
    if not callable(target):
        raise TypeError(f"runner is not callable: {runner_path}")
    return target


def _process_entrypoint(
    runner_path: str,
    payload: dict[str, Any],
    event_queue: Any,
    cancel_event: Any,
) -> None:
    sink = ProcessJobSink(event_queue)
    try:
        runner = _load_runner(runner_path)
        result = runner(payload, sink, cancel_event)
        if result is not None and not sink.terminal_emitted:
            sink.emit_result(result)
    except BaseException as exc:  # subprocess boundary: report then exit normally
        sink.emit_error(str(exc), traceback=traceback_module.format_exc())


def _apply_process_message(job: TestJob, message: dict[str, Any]) -> None:
    event = str(message.get("event") or "message")
    data = message.get("data")
    if not isinstance(data, dict):
        data = {"value": data}
    if event == "result":
        job.succeed(data)
        job.emit("result", data)
        return
    if event == "error":
        job.fail(data, cancelled=bool(data.get("cancelled")))
        job.emit("error", data)
        return
    if event == "artifact":
        name = str(data.get("name") or "")
        if name:
            store_artifact(job, name, data.get("value"))
            job.emit("artifact", {"name": name})
        return
    if event == "paused":
        checkpoint = data.get("checkpoint") if isinstance(data.get("checkpoint"), dict) else data
        store_artifact(job, "step_checkpoint", checkpoint)
        job.pause(checkpoint)
        job.emit("paused", {"checkpoint": checkpoint})
        return
    job.emit(event, data)


_lock = threading.RLock()
_jobs: dict[str, TestJob] = {}
_run_token_to_job: dict[str, str] = {}
_run_id_to_job: dict[str, str] = {}


def _request_digest(payload: dict[str, Any]) -> str:
    try:
        raw = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS | orjson.OPT_SERIALIZE_NUMPY)
    except TypeError:
        raw = repr(payload).encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()[:16]


def _snapshot_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    snapshot = copy.deepcopy(payload)
    try:
        raw = orjson.dumps(snapshot, option=orjson.OPT_SORT_KEYS | orjson.OPT_SERIALIZE_NUMPY)
    except Exception as exc:
        raise ValueError("job payload snapshot must be serializable") from exc
    restored = orjson.loads(raw)
    if not isinstance(restored, dict):
        raise ValueError("job payload snapshot must serialize to an object")
    return restored, raw


def create_job(
    *,
    kind: str = "backtest",
    run_token: str,
    owner: str,
    payload: dict[str, Any],
    run_id: str = "",
    workspace_id: str = "",
    view_uuid: str = "",
    lifecycle_policy: str = "",
    page_uuid: str = "",
    cancel_event: threading.Event | None = None,
) -> TestJob:
    kind = str(kind or "").strip()
    run_token = str(run_token).strip()
    page_uuid = str(page_uuid).strip()
    run_id = str(run_id or payload.get("run_id") or run_token).strip()
    workspace_id = str(workspace_id or payload.get("workspace_id") or "").strip()
    view_uuid = str(view_uuid or payload.get("view_uuid") or page_uuid).strip()
    lifecycle_policy = str(
        lifecycle_policy
        or payload.get("lifecycle_policy")
        or ("observer_bound" if page_uuid else "durable")
    ).strip()
    owner = str(owner).strip()
    if not kind or not run_token or not run_id or not owner:
        raise ValueError("test job requires kind, run_token, run_id, and owner")
    retry_of = str(payload.get("_retry_of") or payload.get("retry_of") or "").strip()
    try:
        attempt = int(payload.get("_attempt") or payload.get("attempt") or (2 if retry_of else 1))
    except (TypeError, ValueError):
        attempt = 2 if retry_of else 1
    snapshot, snapshot_bytes = _snapshot_payload(payload)
    job = TestJob(
        job_id=uuid.uuid4().hex,
        kind=kind,
        run_token=run_token,
        run_id=run_id,
        workspace_id=workspace_id,
        page_uuid=page_uuid,
        view_uuid=view_uuid,
        lifecycle_policy=lifecycle_policy,
        retry_of=retry_of,
        attempt=attempt,
        owner=owner,
        request_digest=_request_digest(payload),
        request_snapshot=snapshot,
        request_snapshot_bytes=snapshot_bytes,
        cancel_event=cancel_event or threading.Event(),
    )
    with _lock:
        if run_token in _run_token_to_job:
            raise ValueError(f"run_token already has a test job: {run_token}")
        for existing in _jobs.values():
            if (
                existing.owner == owner
                and lifecycle_policy == "observer_bound"
                and view_uuid
                and existing.view_uuid == view_uuid
                and existing.kind == kind
                and existing.status not in TERMINAL_STATUSES
            ):
                raise JobConflictError(
                    f"active {kind} job already exists for this view",
                    job_id=existing.job_id,
                )
        _jobs[job.job_id] = job
        _run_token_to_job[run_token] = job.job_id
        _run_id_to_job[run_id] = job.job_id
    test_job_store.create_job_record(job=job, retry_of=retry_of, attempt=attempt)
    return job


def submit(job: TestJob, target: Callable[[TestJobSink], None]) -> Future:
    job.execution_mode = "thread"
    test_job_store.update_job_record(job)
    job.emit("execution_mode", {
        "mode": "thread",
        "reason": "route runner uses in-process FactorTester/page-bound objects",
    })

    def _run() -> None:
        sink = TestJobSink(job)
        job.start()
        try:
            if not job.cancel_event.is_set():
                target(sink)
            if job.status == "running":
                sink.emit_result({"success": True, "job_id": job.job_id})
        except Exception as exc:  # pragma: no cover - defensive fallback
            if job.status not in TERMINAL_STATUSES:
                sink.emit_error(str(exc), traceback=traceback_module.format_exc())
        finally:
            job.close()

    future = _EXECUTOR.submit(_run)
    job.future = future
    return future


def submit_process(job: TestJob, runner_path: str, payload: dict[str, Any]) -> Future:
    """Run an importable serializable runner in a child process.

    ``runner_path`` must resolve to a callable with signature
    ``runner(payload, sink, cancel_event)``. The payload is serialized before
    submission so Flask request/page objects and closures fail fast in the
    parent process instead of leaking across the process boundary.
    """
    _load_runner(runner_path)
    try:
        pickle.dumps(payload)
    except Exception as exc:
        raise ValueError("process job payload must be pickle-serializable") from exc

    job.execution_mode = "process"
    job.runner_path = runner_path
    test_job_store.update_job_record(job)
    process_cancel_event = _PROCESS_CONTEXT.Event()
    job.process_cancel_event = process_cancel_event
    event_queue = _PROCESS_CONTEXT.Queue()

    def _drain_events(block: bool = False) -> int:
        count = 0
        while True:
            try:
                message = event_queue.get(timeout=0.05 if block and count == 0 else 0)
            except queue.Empty:
                return count
            if isinstance(message, dict):
                _apply_process_message(job, message)
                count += 1

    def _run() -> None:
        process_slot: int | None = None
        process = None
        cancel_started_at: float | None = None
        try:
            job.dispatcher_pid = os.getpid()
            test_job_store.update_job_record(job)
            while process_slot is None:
                reason = test_job_store.cancel_request(job.job_id)
                if reason:
                    job.request_cancel(reason=reason)
                    return
                process_slot = test_job_store.acquire_process_slot(
                    job_id=job.job_id,
                    dispatcher_pid=os.getpid(),
                    limit=_MAX_PROCESS_WORKERS,
                )
                if process_slot is None:
                    time.sleep(0.1)
            if job.status in TERMINAL_STATUSES:
                return
            if job.cancel_event.is_set():
                job.fail(
                    {"success": False, "error": "test job cancelled before process start", "cancelled": True},
                    cancelled=True,
                )
                job.emit("error", job.error or {})
                return

            job.start()
            process = _PROCESS_CONTEXT.Process(
                target=_process_entrypoint,
                args=(runner_path, payload, event_queue, process_cancel_event),
                daemon=True,
            )
            job.process = process
            process.start()
            job.worker_pid = process.pid
            job.emit("worker", {"pid": process.pid, "runner_path": runner_path})

            while process.is_alive():
                _drain_events(block=True)
                test_job_store.renew_process_slot(slot=process_slot, job_id=job.job_id)
                reason = test_job_store.cancel_request(job.job_id)
                if reason and not job.cancel_event.is_set():
                    job.request_cancel(reason=reason)
                if job.cancel_event.is_set():
                    process_cancel_event.set()
                    if cancel_started_at is None:
                        cancel_started_at = time.monotonic()
                    elif time.monotonic() - cancel_started_at >= _PROCESS_CANCEL_GRACE_SECONDS:
                        process.terminate()
                if job.status in TERMINAL_STATUSES and not job.cancel_requested:
                    break

            process.join(timeout=1.0)
            _drain_events(block=False)
            job.worker_exitcode = process.exitcode

            if job.status not in TERMINAL_STATUSES:
                if job.cancel_requested or process_cancel_event.is_set():
                    error = {
                        "success": False,
                        "error": "test job cancelled",
                        "cancelled": True,
                        "worker_pid": job.worker_pid,
                        "worker_exitcode": process.exitcode,
                    }
                    job.fail(error, cancelled=True)
                    job.emit("error", error)
                elif process.exitcode not in (0, None):
                    error = {
                        "success": False,
                        "error": f"worker process exited with code {process.exitcode}",
                        "traceback": "",
                        "worker_pid": job.worker_pid,
                        "worker_exitcode": process.exitcode,
                    }
                    job.fail(error)
                    job.emit("error", error)
                else:
                    TestJobSink(job).emit_result({"success": True, "job_id": job.job_id})
        except Exception as exc:  # pragma: no cover - defensive fallback
            if job.status not in TERMINAL_STATUSES:
                TestJobSink(job).emit_error(str(exc), traceback=traceback_module.format_exc())
        finally:
            if process is not None and process.is_alive():
                process.terminate()
                process.join(timeout=1.0)
                job.worker_exitcode = process.exitcode
            job.close()
            try:
                event_queue.close()
            except Exception:
                pass
            if process_slot is not None:
                test_job_store.release_process_slot(slot=process_slot, job_id=job.job_id)

    future = _EXECUTOR.submit(_run)
    job.future = future
    return future


def get(job_id: str) -> TestJob | None:
    with _lock:
        return _jobs.get(str(job_id))


def get_by_run_token(run_token: str) -> TestJob | None:
    with _lock:
        job_id = _run_token_to_job.get(str(run_token))
        return _jobs.get(job_id) if job_id else None


def get_by_run_id(run_id: str) -> TestJob | None:
    with _lock:
        job_id = _run_id_to_job.get(str(run_id))
        return _jobs.get(job_id) if job_id else None


def _prune_locked(now: float | None = None) -> None:
    now = time.time() if now is None else now
    expired = [
        job for job in _jobs.values()
        if job.finished_at is not None and now - job.finished_at > _JOB_TTL_SECONDS
        and job.status != "expired"
    ]
    for job in expired:
        job.result = None
        job.error = {
            "success": False,
            "error": "test job result expired",
            "expired": True,
            "ttl_seconds": _JOB_TTL_SECONDS,
        }
        job.status = "expired"
        job.artifacts.clear()
        test_job_store.update_job_record(job)


def store_artifact(job: TestJob, name: str, value: Any) -> None:
    with job._lock:
        job.artifacts[str(name)] = copy.deepcopy(value)
    test_job_store.store_artifact(job_id=job.job_id, name=str(name), value=value)


def get_artifact(job: TestJob, name: str) -> Any:
    with job._lock:
        value = job.artifacts.get(str(name))
        return copy.deepcopy(value)


def load_artifact(*, job_id: str, owner: str, name: str) -> dict[str, Any] | None:
    require_job(job_id, owner)
    return test_job_store.load_artifact(job_id=job_id, name=name)


def resolve_job_for_detail(*, owner: str, job_id: str = "", run_id: str = "") -> TestJob:
    job = get(job_id) if job_id else get_by_run_id(run_id)
    if job is None:
        raise KeyError("test job not found")
    if job.owner != str(owner):
        raise PermissionError("无权访问其他用户的测试任务")
    return job


def list_jobs(
    *,
    owner: str,
    kind: str | None = None,
    workspace_id: str | None = None,
    run_id: str | None = None,
    statuses: set[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    owner = str(owner)
    kind = str(kind or "").strip()
    workspace_id = str(workspace_id or "").strip()
    run_id = str(run_id or "").strip()
    with _lock:
        _prune_locked()
    test_job_store.expire_jobs(ttl_seconds=_JOB_TTL_SECONDS)
    records = test_job_store.list_jobs(
        owner=owner,
        kind=kind,
        workspace_id=workspace_id,
        run_id=run_id,
        statuses=statuses,
        limit=limit,
    )
    return [record.summary() for record in records]


def require_job(job_id: str, owner: str):
    test_job_store.expire_jobs(ttl_seconds=_JOB_TTL_SECONDS)
    with _lock:
        _prune_locked()
    job = get(job_id)
    durable = test_job_store.load_job(job_id) if job is None else None
    target = job or durable
    if target is None:
        raise KeyError("test job not found")
    if target.owner != str(owner):
        raise PermissionError("无权访问其他用户的回测任务")
    return target


def cancel(job_id: str, owner: str) -> bool:
    job = require_job(job_id, owner)
    requested, _ = test_job_store.request_cancel(
        job_id=job_id, owner=owner, reason="explicit_cancel",
    )
    if isinstance(job, TestJob):
        job.request_cancel(reason="explicit_cancel")
    return requested


def expire_view(view_uuid: str, owner: str) -> int:
    count = 0
    records = test_job_store.list_jobs(
        owner=str(owner), statuses={"queued", "running"}, limit=1000,
    )
    for record in records:
        if record.initiator_view_uuid != str(view_uuid) or record.lifecycle_policy != "observer_bound":
            continue
        requested, _ = test_job_store.request_cancel(
            job_id=record.job_id, owner=owner, reason="view_closed",
        )
        live = get(record.job_id)
        if isinstance(live, TestJob):
            live.request_cancel(reason="view_closed")
        if requested:
            count += 1
    return count


def _format_sse_event(event: TestJobEvent) -> str:
    data = orjson.dumps(event.data, option=orjson.OPT_SERIALIZE_NUMPY).decode()
    return f"id: {event.seq}\nevent: {event.event}\ndata: {data}\n\n"


def _format_sse_payload(seq: int, event: str, data: dict[str, Any]) -> str:
    raw = orjson.dumps(data, option=orjson.OPT_SERIALIZE_NUMPY).decode()
    return f"id: {seq}\nevent: {event}\ndata: {raw}\n\n"


def _stream_events(job: TestJob, *, after_seq: int = 0) -> Iterable[str]:
    seq = int(after_seq)
    while True:
        try:
            events = job.wait_for_events(seq)
        except EventGapError as exc:
            yield _format_sse_payload(
                exc.oldest_seq,
                _SSE_GAP_EVENT,
                {
                    "success": False,
                    "error": str(exc),
                    "reset": True,
                    "oldest_seq": exc.oldest_seq,
                    "requested_seq": exc.requested_seq,
                },
            )
            seq = max(0, exc.oldest_seq - 1)
            continue
        for event in events:
            seq = max(seq, event.seq)
            yield _format_sse_event(event)
        if job.closed and not events:
            break


def stream_response(job: TestJob, *, after_seq: int = 0) -> Response:
    if not isinstance(job, TestJob):
        return stream_durable_response(job, after_seq=after_seq)
    return Response(
        stream_with_context(_stream_events(job, after_seq=after_seq)),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _stream_durable_events(job: Any, *, after_seq: int = 0) -> Iterable[str]:
    seq = int(after_seq)
    while True:
        oldest, _ = test_job_store.event_bounds(job.job_id)
        if seq > 0 and oldest > 0 and seq < oldest - 1:
            yield _format_sse_payload(oldest, _SSE_GAP_EVENT, {
                "success": False,
                "error": "requested event cursor is no longer available",
                "reset": True,
                "oldest_seq": oldest,
                "requested_seq": seq,
            })
            seq = oldest - 1
        events = test_job_store.load_events_after(job.job_id, seq)
        for event in events:
            seq = max(seq, int(event["seq"]))
            yield _format_sse_payload(seq, str(event["event"]), dict(event["data"]))
        current = test_job_store.load_job(job.job_id)
        if current is None or (current.status in TERMINAL_STATUSES and not events):
            break
        if not events:
            yield ": keep-alive\n\n"
            time.sleep(0.5)


def stream_durable_response(job: Any, *, after_seq: int = 0) -> Response:
    return Response(
        stream_with_context(_stream_durable_events(job, after_seq=after_seq)),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def deployment_semantics() -> dict[str, Any]:
    """Return explicit operational constraints for the current registry."""
    return {
        "registry": "sqlite_canonical_with_process_local_live_cache",
        "restart_persistent": True,
        "cross_flask_worker_visible": True,
        "requires_sticky_routing": False,
        "view_uuid_role": "observer lease only; observer-bound jobs cancel after close grace",
        "canonical_job_owner": "owner + workspace/context + job_id/run_token in durable SQLite registry",
        "job_ttl_seconds": _JOB_TTL_SECONDS,
        "sse_cursor": {
            "after_query_param": "after",
            "last_event_id_header": "Last-Event-ID",
            "gap_event": _SSE_GAP_EVENT,
        },
        "thread_workers": _MAX_WORKERS,
        "process_workers": _MAX_PROCESS_WORKERS,
        "process_worker_limit_scope": "global per shared SQLite store via renewable slots",
        "process_start_method": _PROCESS_CONTEXT.get_start_method(),
        "process_runner_contract": "importable runner_path + pickle-serializable payload; no Flask/page objects",
        "product_routes_default_execution_mode": "thread",
        "product_routes_process_contract": "only routes with importable serializable runners may advertise execution_mode=process",
    }
