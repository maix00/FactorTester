"""Request-owner orchestration for immutable direct Transfer Attempts."""

from __future__ import annotations

from collections.abc import Mapping

from server.manager.storage.transfers import (
    TransferAttemptStore,
    TransferStore,
    TransferTicketStore,
)
from server.manager.transfers.coordinator_models import (
    DownloadRequest,
    TransferAccess,
    UploadRequest,
)
from server.manager.transfers.models import (
    AttemptRouteSnapshot,
    NewTransfer,
    NewTransferAttempt,
    TransferOperation,
    TransferStatus,
    TransferTicketRole,
)
from server.manager.transfers.planner import (
    NodeEndpoint,
    TransferPlanningRequest,
    plan_transfer,
)


class TransferCoordinator:
    def __init__(
        self,
        *,
        manager_id: str,
        client_data_endpoint: str,
        requests: TransferStore,
        attempts: TransferAttemptStore,
        tickets: TransferTicketStore,
    ) -> None:
        self.manager_id = str(manager_id or "").strip()
        self.client_data_endpoint = str(
            client_data_endpoint or ""
        ).strip().rstrip("/")
        if not self.manager_id or not self.client_data_endpoint:
            raise ValueError("transfer coordinator identity and endpoint are required")
        self.requests = requests
        self.attempts = attempts
        self.tickets = tickets

    def prepare_download(
        self,
        request: DownloadRequest,
        *,
        endpoints: Mapping[str, NodeEndpoint],
        now: float,
        ticket_ttl: float = 15 * 60,
    ) -> TransferAccess:
        return self._prepare(
            request,
            operation=TransferOperation.DOWNLOAD,
            source_server_id=request.storage_server_id,
            destination_server_id=self.manager_id,
            endpoints=endpoints,
            now=now,
            ticket_ttl=ticket_ttl,
        )

    def prepare_upload(
        self,
        request: UploadRequest,
        *,
        endpoints: Mapping[str, NodeEndpoint],
        now: float,
        ticket_ttl: float = 15 * 60,
    ) -> TransferAccess:
        return self._prepare(
            request,
            operation=TransferOperation.UPLOAD,
            source_server_id=self.manager_id,
            destination_server_id=request.storage_server_id,
            endpoints=endpoints,
            now=now,
            ticket_ttl=ticket_ttl,
        )

    def _prepare(
        self,
        request: DownloadRequest | UploadRequest,
        *,
        operation: TransferOperation,
        source_server_id: str,
        destination_server_id: str,
        endpoints: Mapping[str, NodeEndpoint],
        now: float,
        ticket_ttl: float,
    ) -> TransferAccess:
        transfer = self.requests.create(NewTransfer(
            idempotency_key=request.idempotency_key,
            operation=operation,
            principal=request.principal,
            request_owner_manager_id=self.manager_id,
            source_server_id=source_server_id,
            destination_server_id=destination_server_id,
            storage_server_id=request.storage_server_id,
            job_id=request.job_id,
            artifact_name=request.artifact_name,
            expected_size=request.expected_size,
            expected_sha256=request.expected_sha256,
            expires_at=request.expires_at,
        ), now=now)
        attempt = self._attempt(
            transfer, endpoints=endpoints, now=now,
        )
        role = (
            TransferTicketRole.CLIENT_DOWNLOAD
            if operation is TransferOperation.DOWNLOAD
            else TransferTicketRole.CLIENT_UPLOAD
        )
        expiry = min(
            transfer.expires_at,
            attempt.expires_at,
            now + max(1.0, min(3600.0, float(ticket_ttl))),
        )
        ticket = self.tickets.issue(
            transfer_id=transfer.transfer_id,
            attempt_id=attempt.attempt_id,
            role=role,
            principal=transfer.principal,
            node_id="",
            start_offset=attempt.resume_offset,
            end_offset=attempt.expected_size,
            expires_at=expiry,
            max_uses=1 if operation is TransferOperation.UPLOAD else 0,
            now=now,
        )
        action = "download" if operation is TransferOperation.DOWNLOAD else "upload"
        return TransferAccess(
            transfer_id=transfer.transfer_id,
            attempt_id=attempt.attempt_id,
            mode=attempt.mode,
            data_endpoint=self.client_data_endpoint,
            path=f"/v1/transfers/{attempt.attempt_id}/{action}",
            bearer=ticket.bearer,
            expires_at=expiry,
        )

    def _attempt(
        self,
        transfer,
        *,
        endpoints: Mapping[str, NodeEndpoint],
        now: float,
    ):
        if transfer.attempt:
            existing = self.attempts.latest(transfer.transfer_id)
            if existing is not None:
                return existing
        if transfer.status is TransferStatus.CREATED:
            transfer = self.requests.transition(
                transfer.transfer_id,
                TransferStatus.PLANNED,
                expected=TransferStatus.CREATED,
                now=now,
            )
        plan = plan_transfer(TransferPlanningRequest(
            operation=transfer.operation,
            request_owner_manager_id=self.manager_id,
            source_server_id=transfer.source_server_id,
            destination_server_id=transfer.destination_server_id,
            storage_server_id=transfer.storage_server_id,
            client_data_endpoint=self.client_data_endpoint,
        ), endpoints=endpoints, now=now)
        attempt = self.attempts.begin(NewTransferAttempt(
            attempt_key=f"{transfer.transfer_id}:{transfer.attempt + 1}",
            transfer_id=transfer.transfer_id,
            mode=plan.mode,
            request_owner_manager_id=plan.request_owner_manager_id,
            source_server_id=plan.source_server_id,
            destination_server_id=plan.destination_server_id,
            resume_offset=0,
            expires_at=transfer.expires_at,
            routes=AttemptRouteSnapshot(
                client_data_endpoint=plan.client_data_endpoint,
                source_peer_data_endpoint=plan.source_peer_data_endpoint,
                source_peer_control_endpoint=plan.source_peer_control_endpoint,
                destination_peer_data_endpoint=(
                    plan.destination_peer_data_endpoint
                ),
                destination_peer_control_endpoint=(
                    plan.destination_peer_control_endpoint
                ),
            ),
        ), now=now)
        self.requests.transition(
            transfer.transfer_id,
            TransferStatus.DISPATCHED,
            expected=TransferStatus.PLANNED,
            now=now,
        )
        return attempt


__all__ = [
    "DownloadRequest", "TransferAccess", "TransferCoordinator", "UploadRequest",
]
