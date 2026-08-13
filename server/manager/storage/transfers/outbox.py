"""Transactional outbox leasing for Manager-to-Manager transfer commands."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from server.manager.transfers.models import OutboxMessage


def claim_messages(
    connection: sqlite3.Connection,
    *,
    claimant: str,
    limit: int,
    now: float,
    lease_expires_at: float,
) -> list[OutboxMessage]:
    rows = connection.execute(
        """
        SELECT * FROM transfer_outbox
        WHERE delivered_at IS NULL
          AND (lease_expires_at IS NULL OR lease_expires_at<=?)
        ORDER BY created_at, outbox_id
        LIMIT ?
        """,
        (now, limit),
    ).fetchall()
    for row in rows:
        connection.execute(
            """
            UPDATE transfer_outbox
            SET lease_owner=?, lease_expires_at=?, attempt=attempt+1
            WHERE outbox_id=?
            """,
            (claimant, lease_expires_at, str(row["outbox_id"])),
        )
    return [
        OutboxMessage(
            outbox_id=str(row["outbox_id"]),
            transfer_id=str(row["transfer_id"]),
            event_type=str(row["event_type"]),
            target_manager_id=str(row["target_manager_id"]),
            payload=_payload(str(row["payload_json"])),
            attempt=int(row["attempt"]) + 1,
            lease_owner=claimant,
            lease_expires_at=lease_expires_at,
        )
        for row in rows
    ]


def acknowledge_message(
    connection: sqlite3.Connection,
    *,
    outbox_id: str,
    claimant: str,
    now: float,
) -> None:
    row = connection.execute(
        "SELECT lease_owner, delivered_at FROM transfer_outbox WHERE outbox_id=?",
        (outbox_id,),
    ).fetchone()
    if row is None:
        raise KeyError("transfer outbox message not found")
    if str(row["lease_owner"]) != claimant:
        raise RuntimeError("transfer outbox lease owner changed")
    if row["delivered_at"] is not None:
        return
    connection.execute(
        """
        UPDATE transfer_outbox
        SET delivered_at=?, lease_expires_at=NULL, last_error=''
        WHERE outbox_id=?
        """,
        (now, outbox_id),
    )


def _payload(raw: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):  # pragma: no cover - repository invariant
        raise RuntimeError("transfer outbox payload is invalid")
    return value
