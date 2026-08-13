from __future__ import annotations

from dataclasses import replace

import pytest

from server.manager.storage.transfers import TransferStore
from server.manager.transfers.models import (
    NewTransfer,
    TransferOperation,
    TransferStatus,
)


def _request(**changes) -> NewTransfer:
    value = NewTransfer(
        idempotency_key="alice:job-1:result:download",
        operation=TransferOperation.DOWNLOAD,
        principal="alice",
        request_owner_manager_id="node-b",
        source_server_id="node-a",
        destination_server_id="node-b",
        storage_server_id="node-a",
        job_id="job-1",
        artifact_name="result.bin",
        expected_size=6,
        expected_sha256=(
            "bef57ec7f53a6d40beb640a780a639c83bc29ac8"
            "a9816f1fc6c5c6dcd93c4721"
        ),
        expires_at=200.0,
    )
    return replace(value, **changes)


def test_transfer_request_survives_manager_restart(tmp_path) -> None:
    path = tmp_path / "transfers.sqlite"
    created = TransferStore(path, server_id="node-b").create(
        _request(), now=100.0,
    )

    restored = TransferStore(path, server_id="node-b").require(
        created.transfer_id,
    )

    assert restored == created
    assert restored.request_owner_manager_id == "node-b"
    assert restored.storage_server_id == "node-a"


def test_transfer_creation_is_idempotent_but_rejects_conflicting_content(
    tmp_path,
) -> None:
    store = TransferStore(tmp_path / "transfers.sqlite", server_id="node-b")
    request = _request()

    first = store.create(request, now=100.0)
    duplicate = store.create(request, now=101.0)

    assert duplicate == first
    with pytest.raises(ValueError, match="idempotency key conflicts"):
        store.create(
            replace(request, artifact_name="different.bin"), now=102.0,
        )


def test_transfer_state_changes_are_guarded_and_replay_safe(tmp_path) -> None:
    store = TransferStore(tmp_path / "transfers.sqlite", server_id="node-b")
    transfer = store.create(_request(idempotency_key="transfer-state"), now=100.0)

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
