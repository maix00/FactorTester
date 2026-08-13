"""Request-owner policy for one source-push producer capability."""

from __future__ import annotations

import time

from server.manager.storage.transfers import (
    TransferAttemptStore,
    TransferStore,
    TransferTicketStore,
)
from server.manager.transfers.models import (
    IssuedTransferTicket,
    TransferMode,
    TransferTicketRole,
)


class ProducerTicketIssuer:
    def __init__(
        self,
        *,
        manager_id: str,
        requests: TransferStore,
        attempts: TransferAttemptStore,
        tickets: TransferTicketStore,
    ) -> None:
        self.manager_id = str(manager_id or "").strip()
        self.requests = requests
        self.attempts = attempts
        self.tickets = tickets

    def issue(
        self,
        *,
        attempt_id: str,
        source_node_id: str,
        now: float | None = None,
        ttl: float = 5 * 60,
    ) -> tuple[IssuedTransferTicket, str]:
        current = time.time() if now is None else float(now)
        attempt = self.attempts.require(attempt_id)
        transfer = self.requests.require(attempt.transfer_id)
        source = str(source_node_id or "").strip()
        if transfer.request_owner_manager_id != self.manager_id:
            raise PermissionError("producer ticket is not owned by this Manager")
        if attempt.mode is not TransferMode.SOURCE_PUSH:
            raise PermissionError("Attempt does not accept a source push")
        if source != attempt.source_server_id:
            raise PermissionError("producer identity is not the Attempt source")
        expiry = min(
            transfer.expires_at,
            attempt.expires_at,
            current + max(1.0, min(900.0, float(ttl))),
        )
        issued = self.tickets.issue(
            transfer_id=transfer.transfer_id,
            attempt_id=attempt.attempt_id,
            role=TransferTicketRole.PRODUCER,
            principal=transfer.principal,
            node_id=source,
            start_offset=attempt.resume_offset,
            end_offset=attempt.expected_size,
            expires_at=expiry,
            max_uses=1,
            now=current,
        )
        return issued, attempt.relay_data_endpoint
