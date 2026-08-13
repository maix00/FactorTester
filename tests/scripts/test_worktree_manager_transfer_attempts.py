from __future__ import annotations

from dataclasses import replace

import pytest

from server.manager.storage.transfers import TransferStore
from server.manager.storage.transfers.attempts import TransferAttemptStore
from server.manager.transfers.models import (
    AttemptStatus,
    NewTransfer,
    NewTransferAttempt,
    TransferMode,
    TransferOperation,
    TransferStatus,
)


def _planned_transfer(tmp_path):
    path = tmp_path / "transfers.sqlite"
    requests = TransferStore(path, server_id="public-b2")
    transfer = requests.create(
        NewTransfer(
            idempotency_key="attempt-parent",
            operation=TransferOperation.DOWNLOAD,
            principal="alice",
            request_owner_manager_id="public-b2",
            relay_owner_manager_id="public-b2",
            source_server_id="office-a",
            destination_server_id="public-b2",
            storage_server_id="office-a",
            job_id="job-1",
            artifact_name="result",
            expected_size=12,
            expected_sha256="a" * 64,
            expires_at=300.0,
        ),
        dispatch_to="public-b1",
        now=100.0,
    )
    requests.transition(
        transfer.transfer_id, TransferStatus.PLANNED, now=101.0,
    )
    return path, requests, transfer


def test_attempt_topology_is_durable_idempotent_and_fixed(tmp_path) -> None:
    path, _requests, transfer = _planned_transfer(tmp_path)
    store = TransferAttemptStore(path, server_id="public-b2")
    plan = NewTransferAttempt(
        attempt_key="attempt-parent:1",
        transfer_id=transfer.transfer_id,
        mode=TransferMode.SOURCE_PUSH,
        relay_owner_manager_id="public-b2",
        connection_owner_manager_id="public-b1",
        source_server_id="office-a",
        destination_server_id="public-b2",
        resume_offset=4,
        expires_at=220.0,
    )

    first = store.begin(plan, now=102.0)
    duplicate = TransferAttemptStore(path, server_id="public-b2").begin(
        plan, now=103.0,
    )

    assert duplicate == first
    assert first.ordinal == 1
    assert first.status is AttemptStatus.PLANNED
    assert first.expected_size == 12
    assert first.expected_sha256 == "a" * 64
    with pytest.raises(ValueError, match="attempt key conflicts"):
        store.begin(
            replace(plan, relay_owner_manager_id="public-b3"), now=104.0,
        )


def test_new_attempt_requires_previous_attempt_to_be_terminal(tmp_path) -> None:
    path, requests, transfer = _planned_transfer(tmp_path)
    store = TransferAttemptStore(path, server_id="public-b2")
    first = store.begin(
        NewTransferAttempt(
            attempt_key="attempt-parent:1",
            transfer_id=transfer.transfer_id,
            mode=TransferMode.SOURCE_PUSH,
            relay_owner_manager_id="public-b2",
            connection_owner_manager_id="public-b1",
            source_server_id="office-a",
            destination_server_id="public-b2",
            resume_offset=0,
            expires_at=220.0,
        ),
        now=102.0,
    )

    with pytest.raises(RuntimeError, match="active attempt"):
        store.begin(
            NewTransferAttempt(
                attempt_key="attempt-parent:2",
                transfer_id=transfer.transfer_id,
                mode=TransferMode.DIRECT_PULL,
                relay_owner_manager_id="public-b2",
                connection_owner_manager_id="",
                source_server_id="office-a",
                destination_server_id="public-b2",
                resume_offset=0,
                expires_at=240.0,
            ),
            now=103.0,
        )

    store.transition(first.attempt_id, AttemptStatus.FAILED, now=104.0)
    requests.transition(
        transfer.transfer_id, TransferStatus.RETRY_WAIT, now=104.0,
    )
    requests.transition(
        transfer.transfer_id, TransferStatus.PLANNED, now=105.0,
    )
    second = store.begin(
        NewTransferAttempt(
            attempt_key="attempt-parent:2",
            transfer_id=transfer.transfer_id,
            mode=TransferMode.DIRECT_PULL,
            relay_owner_manager_id="public-b2",
            connection_owner_manager_id="",
            source_server_id="office-a",
            destination_server_id="public-b2",
            resume_offset=4,
            expires_at=240.0,
        ),
        now=106.0,
    )

    assert second.ordinal == 2
    assert second.mode is TransferMode.DIRECT_PULL
