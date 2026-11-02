"""Versioned JSON codec for immutable Transfer and Attempt context."""

from __future__ import annotations

from dataclasses import fields

from server.manager.transfers.models import (
    AttemptRouteSnapshot,
    AttemptStatus,
    TransferAttemptRecord,
    TransferMode,
    TransferOperation,
    TransferRecord,
    TransferStatus,
)
from server.manager.transfers.media_types import normalize_content_type


def transfer_context_payload(
    transfer: TransferRecord,
    attempt: TransferAttemptRecord,
) -> dict[str, object]:
    version = 2 if transfer.principal_identity_id else 1
    return {
        "schema_version": version,
        "transfer": {
            field.name: getattr(transfer, field.name)
            for field in fields(transfer)
            if version == 2 or field.name != "principal_identity_id"
        } | {
            "operation": transfer.operation.value,
            "status": transfer.status.value,
        },
        "attempt": ({
            field.name: getattr(attempt, field.name)
            for field in fields(attempt)
            if field.name != "routes"
        } | {
            "mode": attempt.mode.value,
            "status": attempt.status.value,
            "routes": {
                field.name: getattr(attempt.routes, field.name)
                for field in fields(attempt.routes)
            },
        }),
    }


def parse_transfer_context(
    payload: dict[str, object],
) -> tuple[TransferRecord, TransferAttemptRecord]:
    version = payload.get("schema_version")
    if type(version) is not int or version not in {1, 2}:
        raise ValueError("unsupported transfer context schema")
    transfer_value = payload.get("transfer")
    attempt_value = payload.get("attempt")
    if not isinstance(transfer_value, dict) or not isinstance(attempt_value, dict):
        raise ValueError("transfer context requires transfer and Attempt objects")
    if version == 1 and "principal_identity_id" in transfer_value:
        raise ValueError("legacy transfer context cannot claim a stable identity")
    if version == 2:
        from server.manager.storage.transfers.records import stable_identity_id
        raw_identity = transfer_value.get("principal_identity_id")
        if not isinstance(raw_identity, str) or not raw_identity or stable_identity_id(raw_identity) != raw_identity:
            raise ValueError("transfer context stable identity is invalid")
    try:
        transfer = TransferRecord(
            **transfer_value | {
                "operation": TransferOperation(transfer_value["operation"]),
                "status": TransferStatus(transfer_value["status"]),
                "content_type": normalize_content_type(
                    transfer_value.get("content_type")
                ),
            }
        )
        attempt = TransferAttemptRecord(
            **attempt_value | {
                "mode": TransferMode(attempt_value["mode"]),
                "status": AttemptStatus(attempt_value["status"]),
                "routes": AttemptRouteSnapshot(
                    **(
                        attempt_value.get("routes")
                        if isinstance(attempt_value.get("routes"), dict)
                        else {}
                    )
                ),
            }
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("transfer context fields are invalid") from exc
    return transfer, attempt
