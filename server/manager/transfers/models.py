"""Stable values shared by transfer planning, persistence, and transport."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class TransferOperation(StrEnum):
    DOWNLOAD = "download"
    UPLOAD = "upload"


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
