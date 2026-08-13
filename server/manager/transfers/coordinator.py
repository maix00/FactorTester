"""Request-owner orchestration for fixed transfer Attempts and capabilities."""

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
)
from server.manager.transfers.models import (
    AttemptRouteSnapshot,
    NewTransfer,
    NewTransferAttempt,
    TransferAttemptRecord,
    TransferOperation,
    TransferMode,
    TransferStatus,
    TransferTicketRole,
)
from server.manager.transfers.planner import (
    NodeReachability,
    TransferPlanningRequest,
    plan_transfer,
)


class TransferCoordinator:
    def __init__(
        self,
        *,
        manager_id: str,
        data_endpoint: str,
        control_endpoint: str = "",
        requests: TransferStore,
        attempts: TransferAttemptStore,
        tickets: TransferTicketStore,
        command_dispatcher=None,
    ) -> None:
        self.manager_id = str(manager_id or "").strip()
        self.data_endpoint = str(data_endpoint or "").strip().rstrip("/")
        self.control_endpoint = str(control_endpoint or "").strip().rstrip("/")
        if not self.manager_id or not self.data_endpoint:
            raise ValueError("transfer coordinator identity and endpoint are required")
        self.requests = requests
        self.attempts = attempts
        self.tickets = tickets
        self.command_dispatcher = command_dispatcher

    def prepare_download(
        self,
        request: DownloadRequest,
        *,
        observations: Mapping[str, NodeReachability],
        now: float,
        ticket_ttl: float = 15 * 60,
    ) -> TransferAccess:
        transfer = self.requests.create(
            NewTransfer(
                idempotency_key=request.idempotency_key,
                operation=TransferOperation.DOWNLOAD,
                principal=request.principal,
                request_owner_manager_id=self.manager_id,
                relay_owner_manager_id=self.manager_id,
                source_server_id=request.storage_server_id,
                destination_server_id=self.manager_id,
                storage_server_id=request.storage_server_id,
                job_id=request.job_id,
                artifact_name=request.artifact_name,
                expected_size=request.expected_size,
                expected_sha256=request.expected_sha256,
                expires_at=request.expires_at,
            ),
            dispatch_to=self.manager_id,
            now=now,
        )
        attempt = self._attempt_for_download(
            transfer,
            observations=observations,
            now=now,
        )
        # Planning transitions the durable request to dispatched.  Always
        # build an at-least-once command from the authoritative post-transition
        # row so a retry produces the same canonical payload hash.
        transfer = self.requests.require(transfer.transfer_id)
        if attempt.mode in {
            TransferMode.SOURCE_PUSH,
            TransferMode.DESTINATION_PULL,
        }:
            if self.command_dispatcher is None:
                raise ConnectionError(
                    f"{attempt.mode.value} command dispatcher is unavailable"
                )
            self.command_dispatcher.dispatch(transfer, attempt)
        expiry = min(
            transfer.expires_at,
            attempt.expires_at,
            now + max(1.0, min(3600.0, float(ticket_ttl))),
        )
        ticket = self.tickets.issue(
            transfer_id=transfer.transfer_id,
            attempt_id=attempt.attempt_id,
            role=TransferTicketRole.CONSUMER,
            principal=transfer.principal,
            node_id="",
            start_offset=attempt.resume_offset,
            end_offset=attempt.expected_size,
            expires_at=expiry,
            now=now,
        )
        return TransferAccess(
            transfer_id=transfer.transfer_id,
            attempt_id=attempt.attempt_id,
            mode=attempt.mode,
            data_endpoint=self.data_endpoint,
            path=f"/v1/transfers/{attempt.attempt_id}/consumer",
            bearer=ticket.bearer,
            expires_at=expiry,
        )

    def _attempt_for_download(
        self,
        transfer,
        *,
        observations: Mapping[str, NodeReachability],
        now: float,
    ) -> TransferAttemptRecord:
        if transfer.attempt:
            attempt = self.attempts.latest(transfer.transfer_id)
            if attempt is not None:
                return attempt
        if transfer.status is TransferStatus.CREATED:
            transfer = self.requests.transition(
                transfer.transfer_id,
                TransferStatus.PLANNED,
                expected=TransferStatus.CREATED,
                now=now,
            )
        plan = plan_transfer(
            TransferPlanningRequest(
                operation=TransferOperation.DOWNLOAD,
                relay_owner_manager_id=self.manager_id,
                source_server_id=transfer.source_server_id,
                destination_server_id=transfer.destination_server_id,
                storage_server_id=transfer.storage_server_id,
                relay_data_endpoint=self.data_endpoint,
                request_owner_control_endpoint=self.control_endpoint,
            ),
            observations=observations,
            now=now,
        )
        attempt = self.attempts.begin(
            NewTransferAttempt(
                attempt_key=f"{transfer.transfer_id}:1",
                transfer_id=transfer.transfer_id,
                mode=plan.mode,
                relay_owner_manager_id=plan.relay_owner_manager_id,
                connection_owner_manager_id=plan.connection_owner_manager_id,
                source_server_id=plan.source_server_id,
                destination_server_id=plan.destination_server_id,
                resume_offset=0,
                expires_at=transfer.expires_at,
                routes=AttemptRouteSnapshot(
                    relay_data_endpoint=plan.relay_data_endpoint,
                    source_data_endpoint=plan.source_data_endpoint,
                    source_control_endpoint=plan.source_control_endpoint,
                    destination_data_endpoint=plan.destination_data_endpoint,
                    destination_control_endpoint=(
                        plan.destination_control_endpoint
                    ),
                    request_owner_control_endpoint=(
                        plan.request_owner_control_endpoint
                    ),
                    connection_owner_control_endpoint=(
                        plan.connection_owner_control_endpoint
                    ),
                ),
            ),
            now=now,
        )
        self.requests.transition(
            transfer.transfer_id,
            TransferStatus.DISPATCHED,
            expected=TransferStatus.PLANNED,
            now=now,
        )
        return attempt


__all__ = ["DownloadRequest", "TransferAccess", "TransferCoordinator"]
