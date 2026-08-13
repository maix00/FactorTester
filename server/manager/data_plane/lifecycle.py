"""Idempotent lifecycle updates around one data-plane stream."""

from __future__ import annotations

from server.manager.transfers.models import AttemptStatus, TransferStatus
from server.manager.transfers.state_machine import (
    TERMINAL_ATTEMPT_STATUSES,
    TERMINAL_TRANSFER_STATUSES,
)


class TransferLifecycle:
    def __init__(self, *, requests, attempts) -> None:
        self.requests = requests
        self.attempts = attempts

    def start(self, attempt_id: str) -> None:
        attempt = self.attempts.require(attempt_id)
        if attempt.status in TERMINAL_ATTEMPT_STATUSES:
            if attempt.status is AttemptStatus.COMPLETED:
                return
            raise RuntimeError(f"transfer Attempt is {attempt.status.value}")
        transfer = self.requests.require(attempt.transfer_id)
        if transfer.status is TransferStatus.RETRY_WAIT:
            transfer = self.requests.transition(
                transfer.transfer_id, TransferStatus.PLANNED,
                expected=TransferStatus.RETRY_WAIT,
            )
        if transfer.status is TransferStatus.CREATED:
            transfer = self.requests.transition(
                transfer.transfer_id, TransferStatus.PLANNED,
                expected=TransferStatus.CREATED,
            )
        if transfer.status is TransferStatus.PLANNED:
            transfer = self.requests.transition(
                transfer.transfer_id, TransferStatus.DISPATCHED,
                expected=TransferStatus.PLANNED,
            )
        if transfer.status is TransferStatus.DISPATCHED:
            self.requests.transition(
                transfer.transfer_id, TransferStatus.STREAMING,
                expected=TransferStatus.DISPATCHED,
            )
        if attempt.status is AttemptStatus.PLANNED:
            self.attempts.transition(attempt_id, AttemptStatus.STREAMING)

    def verify(self, attempt_id: str) -> None:
        attempt = self.attempts.require(attempt_id)
        if attempt.status is AttemptStatus.STREAMING:
            self.attempts.transition(attempt_id, AttemptStatus.VERIFYING)
        transfer = self.requests.require(attempt.transfer_id)
        if transfer.status is TransferStatus.STREAMING:
            self.requests.transition(
                transfer.transfer_id, TransferStatus.VERIFYING,
                expected=TransferStatus.STREAMING,
            )

    def complete(self, attempt_id: str) -> None:
        self.verify(attempt_id)
        attempt = self.attempts.require(attempt_id)
        if attempt.status is AttemptStatus.VERIFYING:
            self.attempts.transition(attempt_id, AttemptStatus.COMPLETED)
        transfer = self.requests.require(attempt.transfer_id)
        if transfer.status is TransferStatus.VERIFYING:
            self.requests.transition(
                transfer.transfer_id, TransferStatus.COMPLETED,
                expected=TransferStatus.VERIFYING,
            )

    def fail(self, attempt_id: str, error: BaseException | str) -> None:
        attempt = self.attempts.require(attempt_id)
        if attempt.status not in TERMINAL_ATTEMPT_STATUSES:
            self.attempts.transition(
                attempt_id, AttemptStatus.FAILED, error=str(error),
            )
        transfer = self.requests.require(attempt.transfer_id)
        if transfer.status in TERMINAL_TRANSFER_STATUSES:
            return
        if transfer.status is TransferStatus.CREATED:
            target = TransferStatus.FAILED
        else:
            target = TransferStatus.RETRY_WAIT
        self.requests.transition(transfer.transfer_id, target)


__all__ = ["TransferLifecycle"]
