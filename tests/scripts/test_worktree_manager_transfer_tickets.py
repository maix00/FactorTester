from __future__ import annotations

import sqlite3

import pytest

from server.manager.storage.transfers.tickets import TransferTicketStore
from server.manager.transfers.models import TransferTicketRole


def test_ticket_is_hash_only_and_bound_to_attempt_role_node_and_range(
    tmp_path,
) -> None:
    path = tmp_path / "transfers.sqlite"
    store = TransferTicketStore(path, server_id="public-b2")
    issued = store.issue(
        transfer_id="transfer-1",
        attempt_id="attempt-1",
        role=TransferTicketRole.ORIGIN_READ,
        principal="alice",
        node_id="office-a",
        start_offset=4,
        end_offset=12,
        expires_at=200.0,
        now=100.0,
    )

    grant = store.verify(
        issued.bearer,
        required_role=TransferTicketRole.ORIGIN_READ,
        attempt_id="attempt-1",
        node_id="office-a",
        start_offset=4,
        end_offset=12,
        now=101.0,
    )

    assert grant.ticket_id == issued.ticket_id
    with sqlite3.connect(path) as connection:
        persisted = connection.execute(
            "SELECT token_hash FROM transfer_tickets WHERE ticket_id=?",
            (issued.ticket_id,),
        ).fetchone()[0]
    assert issued.bearer not in persisted
    with pytest.raises(PermissionError, match="role"):
        store.verify(
            issued.bearer,
            required_role=TransferTicketRole.DESTINATION_WRITE,
            attempt_id="attempt-1",
            node_id="office-a",
            start_offset=4,
            end_offset=12,
            now=102.0,
        )
    with pytest.raises(PermissionError, match="range"):
        store.verify(
            issued.bearer,
            required_role=TransferTicketRole.ORIGIN_READ,
            attempt_id="attempt-1",
            node_id="office-a",
            start_offset=0,
            end_offset=12,
            now=102.0,
        )


def test_ticket_expiry_revocation_and_single_use_are_enforced(tmp_path) -> None:
    store = TransferTicketStore(
        tmp_path / "transfers.sqlite", server_id="public-b2",
    )
    issued = store.issue(
        transfer_id="transfer-1",
        attempt_id="attempt-1",
        role=TransferTicketRole.DESTINATION_WRITE,
        principal="alice",
        node_id="office-a",
        start_offset=0,
        end_offset=8,
        expires_at=110.0,
        max_uses=1,
        now=100.0,
    )

    store.verify(
        issued.bearer,
        required_role=TransferTicketRole.DESTINATION_WRITE,
        attempt_id="attempt-1",
        node_id="office-a",
        start_offset=0,
        end_offset=8,
        consume=True,
        now=101.0,
    )
    with pytest.raises(PermissionError, match="use limit"):
        store.verify(
            issued.bearer,
            required_role=TransferTicketRole.DESTINATION_WRITE,
            attempt_id="attempt-1",
            node_id="office-a",
            start_offset=0,
            end_offset=8,
            consume=True,
            now=102.0,
        )

    expiring = store.issue(
        transfer_id="transfer-2",
        attempt_id="attempt-2",
        role=TransferTicketRole.CLIENT_DOWNLOAD,
        principal="alice",
        node_id="",
        start_offset=0,
        end_offset=0,
        expires_at=105.0,
        now=100.0,
    )
    with pytest.raises(PermissionError, match="expired"):
        store.verify(
            expiring.bearer,
            required_role=TransferTicketRole.CLIENT_DOWNLOAD,
            attempt_id="attempt-2",
            node_id="",
            start_offset=0,
            end_offset=0,
            now=106.0,
        )
    store.revoke(expiring.ticket_id, now=107.0)
