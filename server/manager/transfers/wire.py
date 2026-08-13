"""Versioned JSON codec for immutable Transfer and Attempt context."""

from __future__ import annotations

from dataclasses import fields

from server.manager.transfers.models import (
    AttemptStatus,
    TransferAttemptRecord,
    TransferMode,
    TransferOperation,
    TransferRecord,
    TransferStatus,
)


def transfer_context_payload(
    transfer: TransferRecord,
    attempt: TransferAttemptRecord,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "transfer": {
            field.name: getattr(transfer, field.name)
            for field in fields(transfer)
        } | {
            "operation": transfer.operation.value,
            "status": transfer.status.value,
        },
        "attempt": {
            field.name: getattr(attempt, field.name)
            for field in fields(attempt)
        } | {
            "mode": attempt.mode.value,
            "status": attempt.status.value,
        },
    }


def parse_transfer_context(
    payload: dict[str, object],
) -> tuple[TransferRecord, TransferAttemptRecord]:
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported transfer context schema")
    transfer_value = payload.get("transfer")
    attempt_value = payload.get("attempt")
    if not isinstance(transfer_value, dict) or not isinstance(attempt_value, dict):
        raise ValueError("transfer context requires transfer and Attempt objects")
    try:
        transfer = TransferRecord(
            **transfer_value | {
                "operation": TransferOperation(transfer_value["operation"]),
                "status": TransferStatus(transfer_value["status"]),
            }
        )
        attempt = TransferAttemptRecord(
            **attempt_value | {
                "mode": TransferMode(attempt_value["mode"]),
                "status": AttemptStatus(attempt_value["status"]),
            }
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("transfer context fields are invalid") from exc
    return transfer, attempt
