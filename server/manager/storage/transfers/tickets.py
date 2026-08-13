"""Issue and verify role-scoped, hash-only 7997 bearer capabilities."""

from __future__ import annotations

import hmac
import time
from pathlib import Path

from server.manager.storage.transfers.database import TransferDatabase
from server.manager.storage.transfers.records import required
from server.manager.storage.transfers.ticket_records import (
    grant,
    hash_bearer,
    issued,
    new_bearer,
)
from server.manager.transfers.models import (
    IssuedTransferTicket,
    TransferTicketGrant,
    TransferTicketRole,
)


class TransferTicketStore(TransferDatabase):
    def __init__(self, path: str | Path, *, server_id: str) -> None:
        super().__init__(path, server_id=server_id)

    def issue(
        self,
        *,
        transfer_id: str,
        attempt_id: str,
        role: TransferTicketRole | str,
        principal: str,
        node_id: str,
        start_offset: int,
        end_offset: int,
        expires_at: float,
        max_uses: int = 0,
        now: float | None = None,
    ) -> IssuedTransferTicket:
        current = time.time() if now is None else float(now)
        expiry = float(expires_at)
        if expiry <= current:
            raise ValueError("transfer ticket expiry must be in the future")
        start = int(start_offset)
        end = int(end_offset)
        uses = int(max_uses)
        if start < 0 or end < start:
            raise ValueError("transfer ticket range is invalid")
        if uses < 0:
            raise ValueError("transfer ticket max_uses must not be negative")
        ticket_id, bearer, token_hash = new_bearer()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO transfer_tickets(
                    ticket_id, token_hash, transfer_id, attempt_id, role,
                    principal, node_id, start_offset, end_offset, max_uses,
                    issued_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id, token_hash,
                    required(transfer_id, field="transfer_id"),
                    required(attempt_id, field="attempt_id"),
                    TransferTicketRole(role).value,
                    required(principal, field="principal"),
                    str(node_id or "").strip(), start, end, uses,
                    current, expiry,
                ),
            )
        return issued(ticket_id, bearer)

    def verify(
        self,
        bearer: str,
        *,
        required_role: TransferTicketRole | str,
        attempt_id: str,
        node_id: str,
        start_offset: int,
        end_offset: int,
        consume: bool = False,
        now: float | None = None,
    ) -> TransferTicketGrant:
        current = time.time() if now is None else float(now)
        token_hash = hash_bearer(required(bearer, field="bearer"))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM transfer_tickets WHERE token_hash=?",
                (token_hash,),
            ).fetchone()
            if row is None or not hmac.compare_digest(
                str(row["token_hash"]), token_hash,
            ):
                raise PermissionError("transfer ticket is invalid")
            if row["revoked_at"] is not None:
                raise PermissionError("transfer ticket was revoked")
            if float(row["expires_at"]) <= current:
                raise PermissionError("transfer ticket expired")
            if str(row["role"]) != TransferTicketRole(required_role).value:
                raise PermissionError("transfer ticket role mismatch")
            if str(row["attempt_id"]) != str(attempt_id):
                raise PermissionError("transfer ticket attempt mismatch")
            if str(row["node_id"]) != str(node_id or ""):
                raise PermissionError("transfer ticket node mismatch")
            if (
                int(row["start_offset"]) != int(start_offset)
                or int(row["end_offset"]) != int(end_offset)
            ):
                raise PermissionError("transfer ticket range mismatch")
            next_count = int(row["use_count"]) + (1 if consume else 0)
            maximum = int(row["max_uses"])
            if consume and maximum and next_count > maximum:
                raise PermissionError("transfer ticket use limit exceeded")
            if consume:
                connection.execute(
                    "UPDATE transfer_tickets SET use_count=?, last_used_at=? "
                    "WHERE ticket_id=?",
                    (next_count, current, str(row["ticket_id"])),
                )
        return grant(row, use_count=next_count)

    def revoke(self, ticket_id: str, *, now: float | None = None) -> None:
        current = time.time() if now is None else float(now)
        with self._connect() as connection:
            result = connection.execute(
                "UPDATE transfer_tickets SET revoked_at=COALESCE(revoked_at, ?) "
                "WHERE ticket_id=?",
                (current, required(ticket_id, field="ticket_id")),
            )
        if result.rowcount == 0:
            raise KeyError("transfer ticket not found")

