"""Stable values shared by transfer planning, persistence, and transport."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TransferOperation(StrEnum):
    DOWNLOAD = "download"
    UPLOAD = "upload"


class TransferMode(StrEnum):
    LOCAL = "local"
    DIRECT_PULL = "direct_pull"
    DIRECT_PUSH = "direct_push"


class AttemptStatus(StrEnum):
    PLANNED = "planned"
    STREAMING = "streaming"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class TransferTicketRole(StrEnum):
    CLIENT_DOWNLOAD = "client_download"
    CLIENT_UPLOAD = "client_upload"
    ORIGIN_READ = "origin_read"
    DESTINATION_WRITE = "destination_write"


class TransferStatus(StrEnum):
    CREATED = "created"
    PLANNED = "planned"
    DISPATCHED = "dispatched"
    STREAMING = "streaming"
    VERIFYING = "verifying"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class AttemptRouteSnapshot:
    client_data_endpoint: str = ""
    source_peer_data_endpoint: str = ""
    source_peer_control_endpoint: str = ""
    destination_peer_data_endpoint: str = ""
    destination_peer_control_endpoint: str = ""


@dataclass(frozen=True, slots=True)
class NewTransfer:
    idempotency_key: str
    operation: TransferOperation
    principal: str
    request_owner_manager_id: str
    source_server_id: str
    destination_server_id: str
    storage_server_id: str
    job_id: str
    artifact_name: str
    expected_size: int
    expected_sha256: str
    expires_at: float
    object_kind: str = "job_artifact"
    object_id: str = ""


@dataclass(frozen=True, slots=True)
class TransferRecord:
    transfer_id: str
    idempotency_key: str
    operation: TransferOperation
    status: TransferStatus
    principal: str
    request_owner_manager_id: str
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
    object_kind: str = "job_artifact"
    object_id: str = ""


@dataclass(frozen=True, slots=True)
class NewTransferAttempt:
    attempt_key: str
    transfer_id: str
    mode: TransferMode
    request_owner_manager_id: str
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
    request_owner_manager_id: str
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
