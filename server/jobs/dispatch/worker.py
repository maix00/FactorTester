"""Worker-side claim/execute/close contract for dispatched JobAttempts."""

from __future__ import annotations

from dataclasses import dataclass
import os
import socket
import threading
import uuid
from typing import Any, Protocol

from server.jobs.models import JobRecord
from server.jobs.repository.sqlite import JobRepository
from server.jobs.states import JobStatus

from .contract import DispatchMessage


class DispatchWorkerError(RuntimeError):
    """The message is valid but cannot be executed on this worker."""


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """Terminal outcome reported by the Nautilus-backed executor."""

    result_summary: dict[str, Any]
    error: dict[str, Any] | None = None
    cancelled: bool = False

    @property
    def succeeded(self) -> bool:
        return self.error is None and not self.cancelled


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Read-only controls the executor must consult at batch boundaries."""

    repository: JobRepository
    job_id: str
    attempt: int

    def cancel_requested(self) -> bool:
        return self.repository.cancel_requested(self.job_id, self.attempt)


class JobExecutor(Protocol):
    def execute(
        self, record: JobRecord, message: DispatchMessage, context: ExecutionContext,
    ) -> ExecutionOutcome: ...


class DispatchWorker:
    """Idempotent claim + terminal write; no broker-specific imports."""

    def __init__(self, repository: JobRepository) -> None:
        self.repository = repository

    def execute(
        self,
        message: DispatchMessage,
        executor: JobExecutor,
        *,
        worker_pid: int | None = None,
        worker_id: str = "",
        heartbeat_interval: float = 30.0,
    ) -> dict[str, Any]:
        pid = os.getpid() if worker_pid is None else int(worker_pid)
        owner = worker_id or f"{socket.gethostname()}:{pid}:{uuid.uuid4().hex[:12]}"
        record = self.repository.claim_attempt(
            message.job_id, message.attempt, worker_pid=pid, worker_id=owner,
        )
        if record is None:
            return {"status": "duplicate", "job_id": message.job_id, "attempt": message.attempt}
        stop = threading.Event()

        def heartbeat() -> None:
            interval = max(0.05, float(heartbeat_interval))
            while not stop.wait(interval):
                if not self.repository.heartbeat_attempt(
                    record.job_id, record.attempt, owner,
                ):
                    return

        beat = threading.Thread(target=heartbeat, name="job-lease-heartbeat", daemon=True)
        beat.start()
        try:
            outcome = executor.execute(
                record, message,
                ExecutionContext(self.repository, record.job_id, record.attempt),
            )
        except Exception as exc:
            if self.repository.cancel_requested(record.job_id, record.attempt):
                self.repository.transition(
                    record.job_id, JobStatus.CANCELLED, expected=JobStatus.RUNNING,
                    cancel_reason="cancelled during execution",
                )
                return {"status": "cancelled", "job_id": record.job_id}
            self.repository.transition(
                record.job_id,
                JobStatus.FAILED,
                expected=JobStatus.RUNNING,
                error={
                    "code": "worker_execution_failed",
                    "message": f"{type(exc).__name__}: {exc}",
                },
            )
            return {
                "status": "failed",
                "job_id": record.job_id,
                "attempt": record.attempt,
                "error": {"code": "worker_execution_failed"},
            }
        finally:
            stop.set()
            beat.join(timeout=1.0)
        if outcome.cancelled:
            updated = self.repository.transition(
                record.job_id,
                JobStatus.CANCELLED,
                expected=JobStatus.RUNNING,
                result_summary=outcome.result_summary,
                cancel_reason="cancelled by user",
            )
            return {"status": updated.status.value, "job_id": updated.job_id}
        if outcome.succeeded:
            updated = self.repository.transition(
                record.job_id,
                JobStatus.SUCCEEDED,
                expected=JobStatus.RUNNING,
                result_summary=outcome.result_summary,
            )
            return {"status": updated.status.value, "job_id": updated.job_id}
        self.repository.transition(
            record.job_id,
            JobStatus.FAILED,
            expected=JobStatus.RUNNING,
            result_summary=outcome.result_summary,
            error=outcome.error or {"code": "execution_failed", "message": "execution failed"},
        )
        return {"status": "failed", "job_id": record.job_id, "error": outcome.error}
