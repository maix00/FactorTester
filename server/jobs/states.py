"""Research-job states and allowed lifecycle transitions."""

from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    SUBMITTED = "submitted"
    PLANNING = "planning"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset({
    JobStatus.SUCCEEDED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
})

NON_TERMINAL_STATUSES = frozenset(set(JobStatus) - TERMINAL_STATUSES)

ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    # Input retention happens after the immutable JobAttempt row is created
    # but before worker planning begins.  A persistence failure must therefore
    # be able to terminalize the submitted attempt instead of leaving a Job
    # that can never be executed.
    JobStatus.SUBMITTED: frozenset({
        JobStatus.PLANNING,
        JobStatus.QUEUED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    }),
    JobStatus.PLANNING: frozenset({
        JobStatus.AWAITING_CONFIRMATION,
        JobStatus.QUEUED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    }),
    JobStatus.AWAITING_CONFIRMATION: frozenset({JobStatus.QUEUED, JobStatus.CANCELLED}),
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED}),
    JobStatus.RUNNING: frozenset({
        JobStatus.PAUSED,
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    }),
    JobStatus.PAUSED: frozenset({JobStatus.RUNNING, JobStatus.FAILED, JobStatus.CANCELLED}),
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}


def require_transition(current: JobStatus, target: JobStatus) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"invalid job transition: {current.value} -> {target.value}")
