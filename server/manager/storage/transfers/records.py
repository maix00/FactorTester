"""Validation and SQLite codecs for durable Transfer records."""

from __future__ import annotations

import sqlite3

from server.manager.transfers.models import (
    NewTransfer,
    TransferOperation,
    TransferRecord,
    TransferStatus,
)


def required(value: object, *, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{field} is required")
    return result


def normalize_new(request: NewTransfer, *, now: float) -> NewTransfer:
    try:
        operation = TransferOperation(request.operation)
    except ValueError as exc:
        raise ValueError("transfer operation is invalid") from exc
    expected_size = int(request.expected_size)
    if expected_size < 0:
        raise ValueError("expected_size must not be negative")
    expected_sha256 = str(request.expected_sha256 or "").strip().lower()
    if expected_sha256 and (
        len(expected_sha256) != 64
        or any(value not in "0123456789abcdef" for value in expected_sha256)
    ):
        raise ValueError("expected_sha256 must be a SHA-256 hex digest")
    expires_at = float(request.expires_at)
    if expires_at <= now:
        raise ValueError("transfer request expiry must be in the future")
    return NewTransfer(
        idempotency_key=required(
            request.idempotency_key, field="idempotency_key",
        ),
        operation=operation,
        principal=required(request.principal, field="principal"),
        request_owner_manager_id=required(
            request.request_owner_manager_id,
            field="request_owner_manager_id",
        ),
        relay_owner_manager_id=required(
            request.relay_owner_manager_id, field="relay_owner_manager_id",
        ),
        source_server_id=required(
            request.source_server_id, field="source_server_id",
        ),
        destination_server_id=required(
            request.destination_server_id, field="destination_server_id",
        ),
        storage_server_id=required(
            request.storage_server_id, field="storage_server_id",
        ),
        job_id=str(request.job_id or "").strip(),
        artifact_name=str(request.artifact_name or "").strip(),
        expected_size=expected_size,
        expected_sha256=expected_sha256,
        expires_at=expires_at,
    )


def transfer_record(row: sqlite3.Row) -> TransferRecord:
    return TransferRecord(
        transfer_id=str(row["transfer_id"]),
        idempotency_key=str(row["idempotency_key"]),
        operation=TransferOperation(str(row["operation"])),
        status=TransferStatus(str(row["status"])),
        principal=str(row["principal"]),
        request_owner_manager_id=str(row["request_owner_manager_id"]),
        relay_owner_manager_id=str(row["relay_owner_manager_id"]),
        connection_owner_manager_id=str(row["connection_owner_manager_id"]),
        source_server_id=str(row["source_server_id"]),
        destination_server_id=str(row["destination_server_id"]),
        storage_server_id=str(row["storage_server_id"]),
        job_id=str(row["job_id"]),
        artifact_name=str(row["artifact_name"]),
        expected_size=int(row["expected_size"]),
        expected_sha256=str(row["expected_sha256"]),
        attempt=int(row["attempt"]),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        expires_at=float(row["expires_at"]),
    )


def same_request(row: sqlite3.Row, request: NewTransfer) -> bool:
    """Compare only immutable request identity, never mutable attempt state."""
    return (
        str(row["operation"]) == request.operation.value
        and str(row["principal"]) == request.principal
        and str(row["request_owner_manager_id"])
        == request.request_owner_manager_id
        and str(row["relay_owner_manager_id"])
        == request.relay_owner_manager_id
        and str(row["source_server_id"]) == request.source_server_id
        and str(row["destination_server_id"])
        == request.destination_server_id
        and str(row["storage_server_id"]) == request.storage_server_id
        and str(row["job_id"]) == request.job_id
        and str(row["artifact_name"]) == request.artifact_name
        and int(row["expected_size"]) == request.expected_size
        and str(row["expected_sha256"]) == request.expected_sha256
        and float(row["expires_at"]) == request.expires_at
    )
