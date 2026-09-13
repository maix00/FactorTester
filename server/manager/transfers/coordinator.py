"""Request-owner orchestration for immutable direct Transfer Attempts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import hashlib
import json

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
    AttemptStatus,
    AttemptRouteSnapshot,
    NewTransfer,
    NewTransferAttempt,
    TransferOperation,
    TransferStatus,
    TransferTicketRole,
)
from server.manager.transfers.peer_gateway import PeerControlError
from server.manager.transfers.planner import (
    NodeEndpoint,
    NodeUnavailable,
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
        peer_gateway=None,
        local_resume_offset_provider=None,
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
        self.peer_gateway = peer_gateway
        self.local_resume_offset_provider = local_resume_offset_provider

    def prepare_download(
        self,
        request: DownloadRequest,
        *,
        endpoints: Mapping[str, NodeEndpoint],
        now: float,
        ticket_ttl: float = 15 * 60,
    ) -> TransferAccess:
        # Requests are mirrored into the source Manager's store. The same
        # object/key may be read by distinct Managers or principals there.
        key = str(request.idempotency_key or "").strip()
        if not key:
            raise ValueError("idempotency_key is required")
        scope = json.dumps([self.manager_id, request.principal.strip(), key],
                           ensure_ascii=False, separators=(",", ":"))
        request = replace(request, idempotency_key="download-v2:" +
                          hashlib.sha256(scope.encode()).hexdigest())
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
            content_type=request.content_type,
            object_kind=request.object_kind,
            object_id=request.object_id,
        ), now=now)
        attempt = None
        try:
            attempt = self._attempt(
                transfer, endpoints=endpoints, now=now,
            )
            transfer = self.requests.require(transfer.transfer_id)
            if source_server_id != destination_server_id:
                if self.peer_gateway is None:
                    raise NodeUnavailable(
                        _storage_server_id(transfer),
                        "transfer peer gateway is unavailable",
                    )
                self.peer_gateway.import_context(transfer, attempt)
        except NodeUnavailable as exc:
            self._mark_failed(transfer, attempt, now=now, error=exc)
            raise
        except PeerControlError as exc:
            self._mark_failed(transfer, attempt, now=now, error=exc)
            raise
        except (PermissionError, ValueError) as exc:
            self._mark_failed(transfer, attempt, now=now, error=exc)
            raise
        except (ConnectionError, OSError, TimeoutError) as exc:
            unavailable = NodeUnavailable(
                _storage_server_id(transfer),
                f"WireGuard peer control endpoint is unavailable: {exc}",
            )
            self._mark_failed(transfer, attempt, now=now, error=exc)
            raise unavailable from exc
        if transfer.status is TransferStatus.PLANNED:
            self.requests.transition(
                transfer.transfer_id,
                TransferStatus.DISPATCHED,
                expected=TransferStatus.PLANNED,
                now=now,
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
            resume_offset=attempt.resume_offset,
            expected_size=attempt.expected_size,
        )

    def _mark_failed(
        self,
        transfer,
        attempt,
        *,
        now: float,
        error: BaseException | None = None,
    ) -> None:
        selected_attempt = attempt or self.attempts.latest(transfer.transfer_id)
        if (
            selected_attempt is not None
            and selected_attempt.status is not AttemptStatus.FAILED
        ):
            self.attempts.transition(
                selected_attempt.attempt_id,
                AttemptStatus.FAILED,
                now=now,
                error=str(error or "transfer node is unavailable"),
            )
        current = self.requests.require(transfer.transfer_id)
        if current.status not in {
            TransferStatus.COMPLETED,
            TransferStatus.FAILED,
            TransferStatus.EXPIRED,
            TransferStatus.CANCELLED,
        }:
            self.requests.transition(
                transfer.transfer_id,
                TransferStatus.FAILED,
                now=now,
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
                if existing.status is not AttemptStatus.FAILED:
                    return existing
                if transfer.status is not TransferStatus.RETRY_WAIT:
                    return existing
                resume_offset = self._retry_offset(transfer, existing)
                transfer = self.requests.transition(
                    transfer.transfer_id,
                    TransferStatus.PLANNED,
                    expected=TransferStatus.RETRY_WAIT,
                    now=now,
                )
                return self._begin_attempt(
                    transfer,
                    endpoints=endpoints,
                    now=now,
                    resume_offset=resume_offset,
                )
        if transfer.status is TransferStatus.CREATED:
            transfer = self.requests.transition(
                transfer.transfer_id,
                TransferStatus.PLANNED,
                expected=TransferStatus.CREATED,
                now=now,
            )
        return self._begin_attempt(
            transfer, endpoints=endpoints, now=now, resume_offset=0,
        )

    def _begin_attempt(
        self,
        transfer,
        *,
        endpoints: Mapping[str, NodeEndpoint],
        now: float,
        resume_offset: int,
    ):
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
            resume_offset=resume_offset,
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
        return attempt

    def _retry_offset(self, transfer, attempt) -> int:
        if transfer.operation is TransferOperation.DOWNLOAD:
            return 0
        if transfer.destination_server_id == self.manager_id:
            if self.local_resume_offset_provider is None:
                return 0
            value = self.local_resume_offset_provider(transfer, attempt)
        else:
            if self.peer_gateway is None:
                raise ConnectionError("transfer peer gateway is unavailable")
            value = self.peer_gateway.resume_offset(transfer, attempt)
        selected = int(value)
        # An exact-end offset means the destination committed and verified the
        # file, but the final HTTP response did not reach the request owner.
        # Preserve that durable fact as a zero-byte convergence Attempt.
        if not 0 <= selected <= transfer.expected_size:
            raise ValueError("destination resume offset is invalid")
        return selected


__all__ = [
    "DownloadRequest", "TransferAccess", "TransferCoordinator", "UploadRequest",
]


def _storage_server_id(transfer) -> str:
    return (
        transfer.source_server_id
        if transfer.operation is TransferOperation.DOWNLOAD
        else transfer.destination_server_id
    )
