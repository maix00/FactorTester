"""Validation and SQLite codecs for durable Transfer records."""

from __future__ import annotations

import sqlite3

from server.manager.transfers.models import (
    NewTransfer,
    TransferOperation,
    TransferRecord,
    TransferStatus,
)
from server.manager.objects.models import TransferObjectKind, legacy_object_kind


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
    if (
        len(expected_sha256) != 64
        or any(value not in "0123456789abcdef" for value in expected_sha256)
    ):
        raise ValueError("expected_sha256 must be a complete SHA-256 hex digest")
    expires_at = float(request.expires_at)
    if expires_at <= now:
        raise ValueError("transfer request expiry must be in the future")
    object_kind = TransferObjectKind(request.object_kind or legacy_object_kind(
        request.job_id, request.artifact_name,
    )).value
    object_id = str(request.object_id or "").strip()
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
        object_kind=object_kind,
        object_id=object_id,
    )


def transfer_record(row: sqlite3.Row) -> TransferRecord:
    return TransferRecord(
        transfer_id=str(row["transfer_id"]),
        idempotency_key=str(row["idempotency_key"]),
        operation=TransferOperation(str(row["operation"])),
        status=TransferStatus(str(row["status"])),
        principal=str(row["principal"]),
        request_owner_manager_id=str(row["request_owner_manager_id"]),
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
        object_kind=str(row["object_kind"] or legacy_object_kind(
            str(row["job_id"]), str(row["artifact_name"]),
        ).value),
        object_id=str(row["object_id"] or ""),
    )


def same_request(row: sqlite3.Row, request: NewTransfer) -> bool:
    """Compare only immutable request identity, never mutable attempt state."""
    return (
        str(row["operation"]) == request.operation.value
        and str(row["principal"]) == request.principal
        and str(row["request_owner_manager_id"])
        == request.request_owner_manager_id
        and str(row["source_server_id"]) == request.source_server_id
        and str(row["destination_server_id"])
        == request.destination_server_id
        and str(row["storage_server_id"]) == request.storage_server_id
        and str(row["job_id"]) == request.job_id
        and str(row["artifact_name"]) == request.artifact_name
        and int(row["expected_size"]) == request.expected_size
        and str(row["expected_sha256"]) == request.expected_sha256
        and str(row["object_kind"] or legacy_object_kind(
            str(row["job_id"]), str(row["artifact_name"]),
        ).value) == request.object_kind
        and str(row["object_id"] or "") == request.object_id
    )
