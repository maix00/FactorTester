"""Page-scoped async backtest job registry.

The registry owns the user-visible lifecycle for long-running group backtests.
It intentionally stays in the existing Flask process for the first vertical
slice; framework engines may still use their own isolated worker subprocesses
behind the normal backtest dispatch boundary.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
import hashlib
import os
import threading
import time
import traceback as traceback_module
import uuid
from typing import Any, Callable, Iterable

import orjson
from flask import Response, stream_with_context


TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}
_MAX_EVENTS = int(os.environ.get("GTHT_BACKTEST_JOB_MAX_EVENTS", "2000"))
_MAX_WORKERS = max(1, int(os.environ.get("GTHT_BACKTEST_JOB_WORKERS", "2")))
_JOB_TTL_SECONDS = max(60, int(os.environ.get("GTHT_BACKTEST_JOB_TTL_SECONDS", "86400")))
_EXECUTOR = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="backtest-job")


@dataclass(frozen=True, slots=True)
class BacktestJobEvent:
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
class BacktestJob:
    job_id: str
    run_token: str
    page_uuid: str
    owner: str
    request_digest: str
    cancel_event: threading.Event
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    cancel_requested: bool = False
    future: Future | None = None
    _seq: int = 0
    _events: list[BacktestJobEvent] = field(default_factory=list)
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

    def emit(self, event: str, data: dict[str, Any]) -> BacktestJobEvent:
        with self._condition:
            self._seq += 1
            item = BacktestJobEvent(
                seq=self._seq,
                event=str(event),
                data=dict(data),
                created_at=time.time(),
            )
            self._events.append(item)
            if len(self._events) > _MAX_EVENTS:
                del self._events[: len(self._events) - _MAX_EVENTS]
            self._condition.notify_all()
            return item

    def succeed(self, result: dict[str, Any]) -> None:
        with self._condition:
            self.result = dict(result)
            self.error = None
            self.status = "succeeded"
            self.finished_at = time.time()
            self._condition.notify_all()

    def fail(self, error: dict[str, Any], *, cancelled: bool = False) -> None:
        with self._condition:
            self.error = dict(error)
            self.status = "cancelled" if cancelled else "failed"
            self.finished_at = time.time()
            self._condition.notify_all()

    def request_cancel(self) -> bool:
        with self._condition:
            if self.status in TERMINAL_STATUSES:
                return False
            self.cancel_requested = True
            self.cancel_event.set()
            if self.status == "queued":
                self.fail(
                    {"success": False, "error": "backtest job cancelled before start", "cancelled": True},
                    cancelled=True,
                )
                self.close()
            else:
                self._condition.notify_all()
            return True

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def events_after(self, seq: int = 0) -> list[BacktestJobEvent]:
        with self._lock:
            return [event for event in self._events if event.seq > seq]

    def wait_for_events(self, seq: int, timeout: float = 15.0) -> list[BacktestJobEvent]:
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
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
            return {
                "job_id": self.job_id,
                "run_token": self.run_token,
                "page_uuid": self.page_uuid,
                "status": self.status,
                "cancel_requested": self.cancel_requested,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "request_digest": self.request_digest,
                "event_count": self._seq,
                "latest_event": latest_event,
                "has_result": self.result is not None,
                "has_error": self.error is not None,
            }


class BacktestJobSink:
    """ProgressSink-compatible adapter that records events on a BacktestJob."""

    def __init__(self, job: BacktestJob) -> None:
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

    def close(self) -> None:
        self.job.close()

    def get_response(self) -> Response:
        return stream_response(self.job)


_lock = threading.RLock()
_jobs: dict[str, BacktestJob] = {}
_run_token_to_job: dict[str, str] = {}


def _request_digest(payload: dict[str, Any]) -> str:
    try:
        raw = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS | orjson.OPT_SERIALIZE_NUMPY)
    except TypeError:
        raw = repr(payload).encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()[:16]


def create_job(
    *,
    run_token: str,
    page_uuid: str,
    owner: str,
    payload: dict[str, Any],
    cancel_event: threading.Event | None = None,
) -> BacktestJob:
    run_token = str(run_token).strip()
    page_uuid = str(page_uuid).strip()
    owner = str(owner).strip()
    if not run_token or not page_uuid or not owner:
        raise ValueError("backtest job requires run_token, page_uuid, and owner")
    job = BacktestJob(
        job_id=uuid.uuid4().hex,
        run_token=run_token,
        page_uuid=page_uuid,
        owner=owner,
        request_digest=_request_digest(payload),
        cancel_event=cancel_event or threading.Event(),
    )
    with _lock:
        if run_token in _run_token_to_job:
            raise ValueError(f"run_token already has a backtest job: {run_token}")
        _jobs[job.job_id] = job
        _run_token_to_job[run_token] = job.job_id
    return job


def submit(job: BacktestJob, target: Callable[[BacktestJobSink], None]) -> Future:
    def _run() -> None:
        sink = BacktestJobSink(job)
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


def get(job_id: str) -> BacktestJob | None:
    with _lock:
        return _jobs.get(str(job_id))


def get_by_run_token(run_token: str) -> BacktestJob | None:
    with _lock:
        job_id = _run_token_to_job.get(str(run_token))
        return _jobs.get(job_id) if job_id else None


def _prune_locked(now: float | None = None) -> None:
    now = time.time() if now is None else now
    expired = [
        job_id for job_id, job in _jobs.items()
        if job.finished_at is not None and now - job.finished_at > _JOB_TTL_SECONDS
    ]
    for job_id in expired:
        job = _jobs.pop(job_id, None)
        if job is not None:
            _run_token_to_job.pop(job.run_token, None)


def list_jobs(
    *,
    owner: str,
    page_uuid: str | None = None,
    statuses: set[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    owner = str(owner)
    page_uuid = str(page_uuid or "").strip()
    with _lock:
        _prune_locked()
        jobs = [
            job for job in _jobs.values()
            if job.owner == owner
            and (not page_uuid or job.page_uuid == page_uuid)
            and (statuses is None or job.status in statuses)
        ]
        jobs.sort(key=lambda job: job.created_at, reverse=True)
        return [job.summary() for job in jobs[:max(1, int(limit))]]


def require_job(job_id: str, owner: str) -> BacktestJob:
    job = get(job_id)
    if job is None:
        raise KeyError("backtest job not found")
    if job.owner != str(owner):
        raise PermissionError("无权访问其他用户的回测任务")
    return job


def cancel(job_id: str, owner: str) -> bool:
    return require_job(job_id, owner).request_cancel()


def cancel_run_token(run_token: str, page_uuid: str, owner: str) -> bool:
    job = get_by_run_token(run_token)
    if job is None:
        return False
    if job.page_uuid != str(page_uuid) or job.owner != str(owner):
        raise PermissionError("无权取消其他页面或用户的回测任务")
    return job.request_cancel()


def cancel_page(page_uuid: str) -> int:
    count = 0
    with _lock:
        jobs = [job for job in _jobs.values() if job.page_uuid == str(page_uuid)]
    for job in jobs:
        if job.request_cancel():
            count += 1
    return count


def _format_sse_event(event: BacktestJobEvent) -> str:
    data = orjson.dumps(event.data, option=orjson.OPT_SERIALIZE_NUMPY).decode()
    return f"id: {event.seq}\nevent: {event.event}\ndata: {data}\n\n"


def _stream_events(job: BacktestJob, *, after_seq: int = 0) -> Iterable[str]:
    seq = int(after_seq)
    while True:
        events = job.wait_for_events(seq)
        for event in events:
            seq = max(seq, event.seq)
            yield _format_sse_event(event)
        if job.closed and not events:
            break


def stream_response(job: BacktestJob, *, after_seq: int = 0) -> Response:
    return Response(
        stream_with_context(_stream_events(job, after_seq=after_seq)),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
