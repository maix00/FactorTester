"""JSON and SSE wire representation for durable node commands."""

from __future__ import annotations

import json

from server.manager.transfers.node_models import NodeCommandRecord


def command_payload(value: NodeCommandRecord) -> dict[str, object]:
    return {
        "schema_version": 1,
        "command_id": value.command_id,
        "transfer_id": value.transfer_id,
        "attempt_id": value.attempt_id,
        "command_type": value.command_type,
        "target_server_id": value.target_server_id,
        "sequence": value.sequence,
        "payload": value.payload,
        "expires_at": value.expires_at,
    }


def sse_command(value: NodeCommandRecord) -> bytes:
    encoded = json.dumps(
        command_payload(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (
        f"id: {value.sequence}\n"
        "event: transfer-command\n"
        f"data: {encoded}\n\n"
    ).encode("utf-8")
