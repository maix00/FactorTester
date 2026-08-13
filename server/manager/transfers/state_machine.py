"""Lifecycle rules for one durable Transfer request."""

from __future__ import annotations

from server.manager.transfers.models import AttemptStatus, TransferStatus


TERMINAL_TRANSFER_STATUSES = frozenset({
    TransferStatus.COMPLETED,
    TransferStatus.FAILED,
    TransferStatus.EXPIRED,
    TransferStatus.CANCELLED,
})


ALLOWED_TRANSFER_TRANSITIONS: dict[
    TransferStatus, frozenset[TransferStatus]
] = {
    TransferStatus.CREATED: frozenset({
        TransferStatus.PLANNED,
        TransferStatus.FAILED,
        TransferStatus.EXPIRED,
        TransferStatus.CANCELLED,
    }),
    TransferStatus.PLANNED: frozenset({
        TransferStatus.DISPATCHED,
        TransferStatus.WAITING_PRODUCER,
        TransferStatus.WAITING_CONSUMER,
        TransferStatus.RETRY_WAIT,
        TransferStatus.FAILED,
        TransferStatus.EXPIRED,
        TransferStatus.CANCELLED,
    }),
    TransferStatus.DISPATCHED: frozenset({
        TransferStatus.WAITING_PRODUCER,
        TransferStatus.WAITING_CONSUMER,
        TransferStatus.STREAMING,
        TransferStatus.RETRY_WAIT,
        TransferStatus.FAILED,
        TransferStatus.EXPIRED,
        TransferStatus.CANCELLED,
    }),
    TransferStatus.WAITING_PRODUCER: frozenset({
        TransferStatus.STREAMING,
        TransferStatus.RETRY_WAIT,
        TransferStatus.FAILED,
        TransferStatus.EXPIRED,
        TransferStatus.CANCELLED,
    }),
    TransferStatus.WAITING_CONSUMER: frozenset({
        TransferStatus.STREAMING,
        TransferStatus.RETRY_WAIT,
        TransferStatus.FAILED,
        TransferStatus.EXPIRED,
        TransferStatus.CANCELLED,
    }),
    TransferStatus.STREAMING: frozenset({
        TransferStatus.VERIFYING,
        TransferStatus.RETRY_WAIT,
        TransferStatus.FAILED,
        TransferStatus.EXPIRED,
        TransferStatus.CANCELLED,
    }),
    TransferStatus.VERIFYING: frozenset({
        TransferStatus.COMPLETED,
        TransferStatus.RETRY_WAIT,
        TransferStatus.FAILED,
        TransferStatus.EXPIRED,
        TransferStatus.CANCELLED,
    }),
    TransferStatus.RETRY_WAIT: frozenset({
        TransferStatus.PLANNED,
        TransferStatus.FAILED,
        TransferStatus.EXPIRED,
        TransferStatus.CANCELLED,
    }),
    **{status: frozenset() for status in TERMINAL_TRANSFER_STATUSES},
}


def require_transfer_transition(
    current: TransferStatus,
    target: TransferStatus,
) -> None:
    if target not in ALLOWED_TRANSFER_TRANSITIONS[current]:
        raise ValueError(
            f"invalid transfer transition: {current.value} -> {target.value}"
        )


TERMINAL_ATTEMPT_STATUSES = frozenset({
    AttemptStatus.COMPLETED,
    AttemptStatus.FAILED,
    AttemptStatus.EXPIRED,
    AttemptStatus.CANCELLED,
})


ALLOWED_ATTEMPT_TRANSITIONS: dict[
    AttemptStatus, frozenset[AttemptStatus]
] = {
    AttemptStatus.PLANNED: frozenset({
        AttemptStatus.WAITING_PRODUCER,
        AttemptStatus.WAITING_CONSUMER,
        AttemptStatus.STREAMING,
        *TERMINAL_ATTEMPT_STATUSES,
    }),
    AttemptStatus.WAITING_PRODUCER: frozenset({
        AttemptStatus.STREAMING,
        *TERMINAL_ATTEMPT_STATUSES,
    }),
    AttemptStatus.WAITING_CONSUMER: frozenset({
        AttemptStatus.STREAMING,
        *TERMINAL_ATTEMPT_STATUSES,
    }),
    AttemptStatus.STREAMING: frozenset({
        AttemptStatus.VERIFYING,
        *TERMINAL_ATTEMPT_STATUSES,
    }),
    AttemptStatus.VERIFYING: frozenset({
        AttemptStatus.COMPLETED,
        AttemptStatus.FAILED,
        AttemptStatus.EXPIRED,
        AttemptStatus.CANCELLED,
    }),
    **{status: frozenset() for status in TERMINAL_ATTEMPT_STATUSES},
}


def require_attempt_transition(
    current: AttemptStatus,
    target: AttemptStatus,
) -> None:
    if target not in ALLOWED_ATTEMPT_TRANSITIONS[current]:
        raise ValueError(
            f"invalid attempt transition: {current.value} -> {target.value}"
        )
