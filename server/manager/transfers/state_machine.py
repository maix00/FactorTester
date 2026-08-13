"""Lifecycle guards for durable Transfer requests and Attempts."""

from __future__ import annotations

from server.manager.transfers.models import AttemptStatus, TransferStatus


TERMINAL_TRANSFER_STATUSES = frozenset({
    TransferStatus.COMPLETED,
    TransferStatus.FAILED,
    TransferStatus.EXPIRED,
    TransferStatus.CANCELLED,
})
TERMINAL_ATTEMPT_STATUSES = frozenset({
    AttemptStatus.COMPLETED,
    AttemptStatus.FAILED,
    AttemptStatus.EXPIRED,
    AttemptStatus.CANCELLED,
})


ALLOWED_TRANSFER_TRANSITIONS = {
    TransferStatus.CREATED: frozenset({
        TransferStatus.PLANNED, TransferStatus.FAILED,
        TransferStatus.EXPIRED, TransferStatus.CANCELLED,
    }),
    TransferStatus.PLANNED: frozenset({
        TransferStatus.DISPATCHED, TransferStatus.RETRY_WAIT,
        TransferStatus.FAILED, TransferStatus.EXPIRED,
        TransferStatus.CANCELLED,
    }),
    TransferStatus.DISPATCHED: frozenset({
        TransferStatus.STREAMING, TransferStatus.RETRY_WAIT,
        TransferStatus.FAILED, TransferStatus.EXPIRED,
        TransferStatus.CANCELLED,
    }),
    TransferStatus.STREAMING: frozenset({
        TransferStatus.VERIFYING, TransferStatus.RETRY_WAIT,
        TransferStatus.FAILED, TransferStatus.EXPIRED,
        TransferStatus.CANCELLED,
    }),
    TransferStatus.VERIFYING: frozenset({
        TransferStatus.COMPLETED, TransferStatus.RETRY_WAIT,
        TransferStatus.FAILED, TransferStatus.EXPIRED,
        TransferStatus.CANCELLED,
    }),
    TransferStatus.RETRY_WAIT: frozenset({
        TransferStatus.PLANNED, TransferStatus.FAILED,
        TransferStatus.EXPIRED, TransferStatus.CANCELLED,
    }),
    **{status: frozenset() for status in TERMINAL_TRANSFER_STATUSES},
}

ALLOWED_ATTEMPT_TRANSITIONS = {
    AttemptStatus.PLANNED: frozenset({
        AttemptStatus.STREAMING, *TERMINAL_ATTEMPT_STATUSES,
    }),
    AttemptStatus.STREAMING: frozenset({
        AttemptStatus.VERIFYING, *TERMINAL_ATTEMPT_STATUSES,
    }),
    AttemptStatus.VERIFYING: TERMINAL_ATTEMPT_STATUSES,
    **{status: frozenset() for status in TERMINAL_ATTEMPT_STATUSES},
}


def require_transfer_transition(
    current: TransferStatus,
    target: TransferStatus,
) -> None:
    if target not in ALLOWED_TRANSFER_TRANSITIONS[current]:
        raise ValueError(
            f"invalid transfer transition: {current.value} -> {target.value}"
        )


def require_attempt_transition(
    current: AttemptStatus,
    target: AttemptStatus,
) -> None:
    if target not in ALLOWED_ATTEMPT_TRANSITIONS[current]:
        raise ValueError(
            f"invalid attempt transition: {current.value} -> {target.value}"
        )
