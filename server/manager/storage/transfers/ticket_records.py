"""Hashing and row mapping for short-lived 7997 capabilities."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3

from server.manager.transfers.models import (
    IssuedTransferTicket,
    TransferTicketGrant,
    TransferTicketRole,
)


def new_bearer() -> tuple[str, str, str]:
    ticket_id = secrets.token_hex(16)
    secret = secrets.token_urlsafe(32)
    bearer = f"ftt_{ticket_id}.{secret}"
    return ticket_id, bearer, hash_bearer(bearer)


def hash_bearer(bearer: str) -> str:
    return hashlib.sha256(str(bearer).encode("utf-8")).hexdigest()


def issued(ticket_id: str, bearer: str) -> IssuedTransferTicket:
    return IssuedTransferTicket(ticket_id=ticket_id, bearer=bearer)


def grant(row: sqlite3.Row, *, use_count: int | None = None) -> TransferTicketGrant:
    return TransferTicketGrant(
        ticket_id=str(row["ticket_id"]),
        transfer_id=str(row["transfer_id"]),
        attempt_id=str(row["attempt_id"]),
        role=TransferTicketRole(str(row["role"])),
        principal=str(row["principal"]),
        node_id=str(row["node_id"]),
        start_offset=int(row["start_offset"]),
        end_offset=int(row["end_offset"]),
        expires_at=float(row["expires_at"]),
        use_count=(int(row["use_count"]) if use_count is None else use_count),
        max_uses=int(row["max_uses"]),
    )

