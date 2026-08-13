"""Canonical command payloads and SQLite row codecs."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from server.manager.storage.transfers.records import required
from server.manager.transfers.models import NewTransferCommand, TransferCommandRecord


def canonical_payload(value: dict[str, Any]) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise ValueError("transfer command payload must be an object")
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalize_command(
    value: NewTransferCommand,
    *,
    server_id: str,
    now: float,
) -> tuple[NewTransferCommand, str, str]:
    target = required(value.target_server_id, field="target_server_id")
    if target != server_id:
        raise PermissionError("transfer command targets another server")
    sequence = int(value.sequence)
    if sequence < 0:
        raise ValueError("transfer command sequence must not be negative")
    expires_at = float(value.expires_at)
    if expires_at <= now:
        raise ValueError("transfer command has expired")
    payload_json, payload_hash = canonical_payload(value.payload)
    return (
        NewTransferCommand(
            command_id=required(value.command_id, field="command_id"),
            transfer_id=required(value.transfer_id, field="transfer_id"),
            attempt_id=required(value.attempt_id, field="attempt_id"),
            command_type=required(value.command_type, field="command_type"),
            target_server_id=target,
            sequence=sequence,
            payload=value.payload,
            expires_at=expires_at,
        ),
        payload_json,
        payload_hash,
    )


def command_record(row: sqlite3.Row) -> TransferCommandRecord:
    payload = json.loads(str(row["payload_json"]))
    if not isinstance(payload, dict):  # pragma: no cover - schema invariant
        raise RuntimeError("transfer inbox payload is invalid")
    lease_expiry = row["lease_expires_at"]
    return TransferCommandRecord(
        command_id=str(row["command_id"]),
        transfer_id=str(row["transfer_id"]),
        attempt_id=str(row["attempt_id"]),
        command_type=str(row["command_type"]),
        target_server_id=str(row["target_server_id"]),
        sequence=int(row["sequence"]),
        payload=payload,
        payload_hash=str(row["payload_hash"]),
        status=str(row["status"]),
        delivery_attempt=int(row["delivery_attempt"]),
        lease_owner=str(row["lease_owner"]),
        lease_expires_at=(
            float(lease_expiry) if lease_expiry is not None else None
        ),
        received_at=float(row["received_at"]),
        updated_at=float(row["updated_at"]),
        expires_at=float(row["expires_at"]),
        last_error=str(row["last_error"]),
    )


def same_command(
    row: sqlite3.Row,
    value: NewTransferCommand,
    payload_hash: str,
) -> bool:
    return (
        str(row["transfer_id"]) == value.transfer_id
        and str(row["attempt_id"]) == value.attempt_id
        and str(row["command_type"]) == value.command_type
        and str(row["target_server_id"]) == value.target_server_id
        and int(row["sequence"]) == value.sequence
        and str(row["payload_hash"]) == payload_hash
        and float(row["expires_at"]) == value.expires_at
    )

