"""Validation and SQLite codec for immutable transfer-attempt topology."""

from __future__ import annotations

import sqlite3

from server.manager.storage.transfers.records import required
from server.manager.transfers.models import (
    AttemptRouteSnapshot,
    AttemptStatus,
    NewTransferAttempt,
    TransferAttemptRecord,
    TransferMode,
)


def normalize_attempt(
    value: NewTransferAttempt,
    *,
    expected_size: int,
    now: float,
) -> NewTransferAttempt:
    offset = int(value.resume_offset)
    if offset < 0 or offset > expected_size:
        raise ValueError("resume_offset is outside the transfer range")
    expires_at = float(value.expires_at)
    if expires_at <= now:
        raise ValueError("attempt expiry must be in the future")
    return NewTransferAttempt(
        attempt_key=required(value.attempt_key, field="attempt_key"),
        transfer_id=required(value.transfer_id, field="transfer_id"),
        mode=TransferMode(value.mode),
        request_owner_manager_id=required(
            value.request_owner_manager_id,
            field="request_owner_manager_id",
        ),
        source_server_id=required(
            value.source_server_id, field="source_server_id",
        ),
        destination_server_id=required(
            value.destination_server_id, field="destination_server_id",
        ),
        resume_offset=offset,
        expires_at=expires_at,
        routes=AttemptRouteSnapshot(**{
            field: str(getattr(value.routes, field) or "").strip()
            for field in AttemptRouteSnapshot.__dataclass_fields__
        }),
    )


def attempt_record(row: sqlite3.Row) -> TransferAttemptRecord:
    return TransferAttemptRecord(
        attempt_id=str(row["attempt_id"]),
        attempt_key=str(row["attempt_key"]),
        transfer_id=str(row["transfer_id"]),
        ordinal=int(row["ordinal"]),
        mode=TransferMode(str(row["mode"])),
        status=AttemptStatus(str(row["status"])),
        request_owner_manager_id=str(row["request_owner_manager_id"]),
        source_server_id=str(row["source_server_id"]),
        destination_server_id=str(row["destination_server_id"]),
        routes=AttemptRouteSnapshot(**{
            field: str(row[field])
            for field in AttemptRouteSnapshot.__dataclass_fields__
        }),
        resume_offset=int(row["resume_offset"]),
        expected_size=int(row["expected_size"]),
        expected_sha256=str(row["expected_sha256"]),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        expires_at=float(row["expires_at"]),
        last_error=str(row["last_error"]),
    )


def same_attempt(row: sqlite3.Row, value: NewTransferAttempt) -> bool:
    return (
        str(row["transfer_id"]) == value.transfer_id
        and str(row["mode"]) == value.mode.value
        and str(row["request_owner_manager_id"])
        == value.request_owner_manager_id
        and str(row["source_server_id"]) == value.source_server_id
        and str(row["destination_server_id"]) == value.destination_server_id
        and all(
            str(row[field]) == str(getattr(value.routes, field))
            for field in AttemptRouteSnapshot.__dataclass_fields__
        )
        and int(row["resume_offset"]) == value.resume_offset
        and float(row["expires_at"]) == value.expires_at
    )
