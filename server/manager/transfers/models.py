"""Stable values shared by transfer planning, persistence, and transport."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class TransferOperation(StrEnum):
    DOWNLOAD = "download"
    UPLOAD = "upload"


class TransferMode(StrEnum):
    LOCAL = "local"
    DIRECT_PULL = "direct_pull"
    DIRECT_PUSH = "direct_push"
    SOURCE_PUSH = "source_push"
    DESTINATION_PULL = "destination_pull"


class AttemptStatus(StrEnum):
    PLANNED = "planned"
    WAITING_PRODUCER = "waiting_producer"
    WAITING_CONSUMER = "waiting_consumer"
    STREAMING = "streaming"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class TransferTicketRole(StrEnum):
    PRODUCER = "producer"
    CONSUMER = "consumer"
    ORIGIN_READ = "origin_read"
    DESTINATION_WRITE = "destination_write"


class TransferStatus(StrEnum):
    CREATED = "created"
    PLANNED = "planned"
    DISPATCHED = "dispatched"
    WAITING_PRODUCER = "waiting_producer"
    WAITING_CONSUMER = "waiting_consumer"
    STREAMING = "streaming"
    VERIFYING = "verifying"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class AttemptRouteSnapshot:
    relay_data_endpoint: str = ""
    source_data_endpoint: str = ""
    source_control_endpoint: str = ""
    destination_data_endpoint: str = ""
    destination_control_endpoint: str = ""
    request_owner_control_endpoint: str = ""
    connection_owner_control_endpoint: str = ""


@dataclass(frozen=True, slots=True)
class NewTransfer:
    idempotency_key: str
    operation: TransferOperation
    principal: str
    request_owner_manager_id: str
    relay_owner_manager_id: str
    source_server_id: str
    destination_server_id: str
    storage_server_id: str
    job_id: str
    artifact_name: str
    expected_size: int
    expected_sha256: str
    expires_at: float


@dataclass(frozen=True, slots=True)
class TransferRecord:
    transfer_id: str
    idempotency_key: str
    operation: TransferOperation
    status: TransferStatus
    principal: str
    request_owner_manager_id: str
    relay_owner_manager_id: str
    connection_owner_manager_id: str
    source_server_id: str
    destination_server_id: str
    storage_server_id: str
    job_id: str
    artifact_name: str
    expected_size: int
    expected_sha256: str
    attempt: int
    created_at: float
    updated_at: float
    expires_at: float


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    outbox_id: str
    transfer_id: str
    event_type: str
    target_manager_id: str
    payload: dict[str, Any]
    attempt: int
    lease_owner: str
    lease_expires_at: float


@dataclass(frozen=True, slots=True)
class NewTransferAttempt:
    attempt_key: str
    transfer_id: str
    mode: TransferMode
    relay_owner_manager_id: str
    connection_owner_manager_id: str
    source_server_id: str
    destination_server_id: str
    resume_offset: int
    expires_at: float
    routes: AttemptRouteSnapshot = AttemptRouteSnapshot()


@dataclass(frozen=True, slots=True)
class TransferAttemptRecord:
    attempt_id: str
    attempt_key: str
    transfer_id: str
    ordinal: int
    mode: TransferMode
    status: AttemptStatus
    relay_owner_manager_id: str
    connection_owner_manager_id: str
    source_server_id: str
    destination_server_id: str
    resume_offset: int
    expected_size: int
    expected_sha256: str
    created_at: float
    updated_at: float
    expires_at: float
    last_error: str
    routes: AttemptRouteSnapshot = AttemptRouteSnapshot()

    @property
    def relay_data_endpoint(self) -> str:
        return self.routes.relay_data_endpoint

    @property
    def source_data_endpoint(self) -> str:
        return self.routes.source_data_endpoint

    @property
    def source_control_endpoint(self) -> str:
        return self.routes.source_control_endpoint

    @property
    def destination_data_endpoint(self) -> str:
        return self.routes.destination_data_endpoint

    @property
    def destination_control_endpoint(self) -> str:
        return self.routes.destination_control_endpoint

    @property
    def request_owner_control_endpoint(self) -> str:
        return self.routes.request_owner_control_endpoint

    @property
    def connection_owner_control_endpoint(self) -> str:
        return self.routes.connection_owner_control_endpoint


@dataclass(frozen=True, slots=True)
class NewTransferCommand:
    command_id: str
    transfer_id: str
    attempt_id: str
    command_type: str
    target_server_id: str
    sequence: int
    payload: dict[str, Any]
    expires_at: float


@dataclass(frozen=True, slots=True)
class TransferCommandRecord:
    command_id: str
    transfer_id: str
    attempt_id: str
    command_type: str
    target_server_id: str
    sequence: int
    payload: dict[str, Any]
    payload_hash: str
    status: str
    delivery_attempt: int
    lease_owner: str
    lease_expires_at: float | None
    received_at: float
    updated_at: float
    expires_at: float
    last_error: str


@dataclass(frozen=True, slots=True)
class IssuedTransferTicket:
    ticket_id: str
    bearer: str


@dataclass(frozen=True, slots=True)
class TransferTicketGrant:
    ticket_id: str
    transfer_id: str
    attempt_id: str
    role: TransferTicketRole
    principal: str
    node_id: str
    start_offset: int
    end_offset: int
    expires_at: float
    use_count: int
    max_uses: int
