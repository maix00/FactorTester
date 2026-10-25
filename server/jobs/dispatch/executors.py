"""Executor abstraction for Celery-dispatched Job kinds.

Nautilus backtests use the dedicated Nautilus executor; IC and factor
evaluation keep their existing process runner functions behind the same
worker contract.  The router is the single place that maps Job kind to
executor, so the old daemon/worker-pool routing can be removed incrementally.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from server.jobs.models import JobRecord

from .contract import DispatchMessage
from .worker import ExecutionContext, ExecutionOutcome, JobExecutor


class _CancelEvent:
    def __init__(self, context: ExecutionContext) -> None:
        self._context = context

    def is_set(self) -> bool:
        return self._context.cancel_requested()


class _ContextSink:
    """Minimal runner sink; artifacts remain the runner's responsibility."""

    def __init__(self, context: ExecutionContext) -> None:
        self.context = context
        self._sequence = 0
        self.result: Any = None
        self.error: dict[str, Any] | None = None
        self.cancelled = False

    def _progress(self, completed: int, total: int, phase: str, percent: float | None, message: str = "") -> None:
        self._sequence += 1
        if total <= 0:
            value = 0.0
        elif percent is None:
            value = completed / total * 100.0
        else:
            value = float(percent)
        self.context.report_progress(
            sequence=self._sequence, phase=str(phase), completed=int(completed),
            total=int(total), percent=max(0.0, min(100.0, value)), message=str(message),
        )

    def emit_start(self, *, total: int = 1, groups: int = 1, phase: str = "compute", **_kwargs: Any) -> None:
        self._progress(0, total, phase, None, "")

    def emit_progress(self, completed: int, total: int, phase: str, *, percent: float | None = None, message: str = "", **_kwargs: Any) -> None:
        self._progress(completed, total, phase, percent, message)

    def emit_result(self, value: Any, **_kwargs: Any) -> None:
        self._progress(1, 1, "done", 100.0, "")
        self.result = value

    def emit_error(self, message: str, *, error_code: str = "execution_failed", cancelled: bool = False, **_kwargs: Any) -> None:
        if cancelled:
            self.cancelled = True
            return
        self.error = {"code": str(error_code), "message": str(message)}


@dataclass
class ProcessRunnerExecutor:
    """Adapt process-runner functions to the Celery JobExecutor contract."""

    runners: Mapping[str, Callable[[dict[str, Any], Any, Any], None]]

    def execute(self, record: JobRecord, message: DispatchMessage, context: ExecutionContext) -> ExecutionOutcome:
        runner = self.runners.get(str(record.kind))
        if runner is None:
            return ExecutionOutcome({}, error={
                "code": "unsupported_job_kind",
                "message": f"no process runner for Job kind {record.kind!r}",
            })
        if context.cancel_requested():
            return ExecutionOutcome({}, cancelled=True)
        payload = dict(record.job_spec)
        payload.update({
            "kind": record.kind,
            "job_id": record.job_id,
            "attempt": record.attempt,
            "execution_plan": record.execution_plan,
            "execution_plan_hash": record.execution_plan_hash,
            "runner_path": record.runner_path,
            "_owner": record.owner,
        })
        payload.setdefault("run_spec", record.job_spec.get("run_spec"))
        sink = _ContextSink(context)
        runner(payload, sink, _CancelEvent(context))
        if sink.cancelled or context.cancel_requested():
            return ExecutionOutcome(sink.result or {}, cancelled=True)
        if sink.error is not None:
            return ExecutionOutcome(sink.result or {}, error=sink.error)
        if sink.result is None:
            return ExecutionOutcome({}, error={
                "code": "runner_no_result",
                "message": "process runner returned without a result or error",
            })
        return ExecutionOutcome(sink.result)


class JobExecutorRouter:
    """Route each Job kind to its executor; backtest remains explicit."""

    def __init__(self, *, backtest: JobExecutor, process: ProcessRunnerExecutor) -> None:
        self.backtest = backtest
        self.process = process

    def execute(self, record: JobRecord, message: DispatchMessage, context: ExecutionContext) -> ExecutionOutcome:
        if record.kind == "backtest":
            return self.backtest.execute(record, message, context)
        return self.process.execute(record, message, context)
