from __future__ import annotations

from dataclasses import replace

import pytest

from server.manager.storage.transfers import TransferStore
from server.manager.transfers.models import (
    NewTransfer,
    TransferOperation,
    TransferStatus,
)


def test_transfer_request_and_dispatch_survive_manager_restart(tmp_path) -> None:
    path = tmp_path / "transfers.sqlite"
    store = TransferStore(path, server_id="public-b2")

    transfer = store.create(
        NewTransfer(
            idempotency_key="alice:job-1:result:download",
            operation=TransferOperation.DOWNLOAD,
            principal="alice",
            request_owner_manager_id="public-b2",
            relay_owner_manager_id="public-b2",
            source_server_id="office-a",
            destination_server_id="public-b2",
            storage_server_id="office-a",
            job_id="job-1",
            artifact_name="result",
            expected_size=6,
            expected_sha256=("bef57ec7f53a6d40beb640a780a639c83bc29ac8"
                             "a9816f1fc6c5c6dcd93c4721"),
            expires_at=200.0,
        ),
        dispatch_to="public-b1",
        now=100.0,
    )

    restarted = TransferStore(path, server_id="public-b2")
    restored = restarted.require(transfer.transfer_id)
    pending = restarted.claim_outbox(
        claimant="public-b2-dispatcher",
        limit=10,
        lease_seconds=30,
        now=101.0,
    )

    assert restored == transfer
    assert len(pending) == 1
    assert pending[0].transfer_id == transfer.transfer_id
    assert pending[0].target_manager_id == "public-b1"
    assert pending[0].event_type == "transfer.requested"
    assert pending[0].payload["source_server_id"] == "office-a"
    assert pending[0].payload["relay_owner_manager_id"] == "public-b2"


def test_transfer_creation_is_idempotent_but_rejects_conflicting_content(
    tmp_path,
) -> None:
    store = TransferStore(tmp_path / "transfers.sqlite", server_id="public-b2")
    request = NewTransfer(
        idempotency_key="alice:job-1:result:download",
        operation=TransferOperation.DOWNLOAD,
        principal="alice",
        request_owner_manager_id="public-b2",
        relay_owner_manager_id="public-b2",
        source_server_id="office-a",
        destination_server_id="public-b2",
        storage_server_id="office-a",
        job_id="job-1",
        artifact_name="result",
        expected_size=6,
        expected_sha256=("bef57ec7f53a6d40beb640a780a639c83bc29ac8"
                         "a9816f1fc6c5c6dcd93c4721"),
        expires_at=200.0,
    )

    first = store.create(request, dispatch_to="public-b1", now=100.0)
    duplicate = store.create(request, dispatch_to="public-b1", now=101.0)

    assert duplicate == first
    assert len(store.claim_outbox(
        claimant="dispatcher", now=102.0,
    )) == 1
    with pytest.raises(ValueError, match="idempotency key conflicts"):
        store.create(
            replace(request, artifact_name="different"),
            dispatch_to="public-b1",
            now=103.0,
        )


def test_transfer_state_changes_are_guarded_and_replay_safe(tmp_path) -> None:
    store = TransferStore(tmp_path / "transfers.sqlite", server_id="public-b2")
    transfer = store.create(
        NewTransfer(
            idempotency_key="transfer-state",
            operation=TransferOperation.DOWNLOAD,
            principal="alice",
            request_owner_manager_id="public-b2",
            relay_owner_manager_id="public-b2",
            source_server_id="office-a",
            destination_server_id="public-b2",
            storage_server_id="office-a",
            job_id="job-1",
            artifact_name="result",
            expected_size=0,
            expected_sha256="",
            expires_at=200.0,
        ),
        dispatch_to="public-b1",
        now=100.0,
    )

    planned = store.transition(
        transfer.transfer_id,
        TransferStatus.PLANNED,
        expected=TransferStatus.CREATED,
        now=101.0,
    )
    replayed = store.transition(
        transfer.transfer_id,
        TransferStatus.PLANNED,
        expected=TransferStatus.CREATED,
        now=102.0,
    )

    assert planned.status is TransferStatus.PLANNED
    assert replayed == planned
    with pytest.raises(ValueError, match="invalid transfer transition"):
        store.transition(
            transfer.transfer_id,
            TransferStatus.COMPLETED,
            expected=TransferStatus.PLANNED,
            now=103.0,
        )
