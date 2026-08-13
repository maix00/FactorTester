"""Canonical public-Manager node-command values and SQLite codecs."""

from __future__ import annotations

import json

from server.manager.storage.transfers.command_records import canonical_payload
from server.manager.storage.transfers.records import required
from server.manager.transfers.node_models import NewNodeCommand, NodeCommandRecord


def normalize_node_command(
    value: NewNodeCommand,
    *,
    now: float,
) -> tuple[NewNodeCommand, str, str]:
    expiry = float(value.expires_at)
    if expiry <= now:
        raise ValueError("node command expiry must be in the future")
    payload_json, payload_hash = canonical_payload(value.payload)
    return NewNodeCommand(
        idempotency_key=required(
            value.idempotency_key, field="idempotency_key",
        ),
        transfer_id=required(value.transfer_id, field="transfer_id"),
        attempt_id=required(value.attempt_id, field="attempt_id"),
        command_type=required(value.command_type, field="command_type"),
        target_server_id=required(
            value.target_server_id, field="target_server_id",
        ),
        payload=value.payload,
        expires_at=expiry,
    ), payload_json, payload_hash


def node_command_record(row) -> NodeCommandRecord:
    payload = json.loads(str(row["payload_json"]))
    if not isinstance(payload, dict):  # pragma: no cover - schema invariant
        raise RuntimeError("node command payload is invalid")
    acknowledged = row["acknowledged_at"]
    return NodeCommandRecord(
        command_id=str(row["command_id"]),
        idempotency_key=str(row["idempotency_key"]),
        transfer_id=str(row["transfer_id"]),
        attempt_id=str(row["attempt_id"]),
        command_type=str(row["command_type"]),
        target_server_id=str(row["target_server_id"]),
        sequence=int(row["sequence"]),
        payload=payload,
        payload_hash=str(row["payload_hash"]),
        created_at=float(row["created_at"]),
        expires_at=float(row["expires_at"]),
        acknowledged_at=(
            float(acknowledged) if acknowledged is not None else None
        ),
    )


def same_node_command(
    row,
    value: NewNodeCommand,
    payload_hash: str,
) -> bool:
    return (
        str(row["transfer_id"]) == value.transfer_id
        and str(row["attempt_id"]) == value.attempt_id
        and str(row["command_type"]) == value.command_type
        and str(row["target_server_id"]) == value.target_server_id
        and str(row["payload_hash"]) == payload_hash
        and float(row["expires_at"]) == value.expires_at
    )

