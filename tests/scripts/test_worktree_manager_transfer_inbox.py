from __future__ import annotations

from dataclasses import replace

import pytest

from server.manager.storage.transfers.inbox import TransferInboxStore
from server.manager.transfers.models import NewTransferCommand


def _command() -> NewTransferCommand:
    return NewTransferCommand(
        command_id="command-1",
        transfer_id="transfer-1",
        attempt_id="attempt-1",
        command_type="source.push",
        target_server_id="office-a",
        sequence=7,
        payload={"relay_endpoint": "https://public-b2:7997"},
        expires_at=200.0,
    )


def test_inbox_persists_idempotent_command_and_rejects_conflict(tmp_path) -> None:
    path = tmp_path / "transfers.sqlite"
    store = TransferInboxStore(path, server_id="office-a")

    first = store.receive(_command(), now=100.0)
    duplicate = TransferInboxStore(path, server_id="office-a").receive(
        _command(), now=101.0,
    )

    assert duplicate == first
    with pytest.raises(ValueError, match="command id conflicts"):
        store.receive(
            replace(_command(), payload={"relay_endpoint": "changed"}),
            now=102.0,
        )


def test_inbox_lease_survives_restart_and_completion_is_owner_bound(tmp_path) -> None:
    path = tmp_path / "transfers.sqlite"
    store = TransferInboxStore(path, server_id="office-a")
    store.receive(_command(), now=100.0)

    claimed = store.claim(claimant="agent-a", now=101.0)[0]
    assert claimed.delivery_attempt == 1
    assert TransferInboxStore(path, server_id="office-a").claim(
        claimant="agent-b", now=105.0,
    ) == []
    with pytest.raises(RuntimeError, match="lease owner"):
        store.complete(claimed.command_id, claimant="agent-b", now=106.0)

    store.complete(claimed.command_id, claimant="agent-a", now=107.0)
    assert store.claim(claimant="agent-c", now=140.0) == []


def test_failed_execution_is_released_only_after_retry_delay(tmp_path) -> None:
    store = TransferInboxStore(
        tmp_path / "transfers.sqlite", server_id="office-a",
    )
    store.receive(_command(), now=100.0)
    claimed = store.claim(claimant="agent-a", now=101.0)[0]

    store.retry(
        claimed.command_id,
        claimant="agent-a",
        error="relay unavailable",
        delay=5,
        now=102.0,
    )

    assert store.claim(claimant="agent-b", now=106.9) == []
    retried = store.claim(claimant="agent-b", now=107.0)[0]
    assert retried.delivery_attempt == 2
    assert retried.last_error == "relay unavailable"
