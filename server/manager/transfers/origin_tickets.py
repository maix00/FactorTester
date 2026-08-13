"""Source-Manager policy for issuing short-lived origin-read capabilities."""

from __future__ import annotations

import time

from server.manager.storage.transfers import (
    TransferReplicaStore,
    TransferTicketStore,
)
from server.manager.transfers.models import IssuedTransferTicket, TransferTicketRole


class OriginTicketIssuer:
    def __init__(
        self,
        *,
        manager_id: str,
        replicas: TransferReplicaStore,
        tickets: TransferTicketStore,
    ) -> None:
        self.manager_id = str(manager_id or "").strip()
        self.replicas = replicas
        self.tickets = tickets

    def issue(
        self,
        *,
        attempt_id: str,
        requester_node_id: str,
        now: float | None = None,
        ttl: float = 5 * 60,
    ) -> IssuedTransferTicket:
        current = time.time() if now is None else float(now)
        transfer, attempt = self.replicas.require_context(attempt_id)
        requester = str(requester_node_id or "").strip()
        if transfer.source_server_id != self.manager_id:
            raise PermissionError("origin ticket source server mismatch")
        if requester != transfer.request_owner_manager_id:
            raise PermissionError("origin ticket requester is not request owner")
        expiry = min(
            transfer.expires_at,
            attempt.expires_at,
            current + max(1.0, min(900.0, float(ttl))),
        )
        return self.tickets.issue(
            transfer_id=transfer.transfer_id,
            attempt_id=attempt.attempt_id,
            role=TransferTicketRole.ORIGIN_READ,
            principal=transfer.principal,
            node_id=requester,
            start_offset=attempt.resume_offset,
            end_offset=attempt.expected_size,
            expires_at=expiry,
            max_uses=0,
            now=current,
        )
