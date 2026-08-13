from __future__ import annotations

import pytest

from server.manager.storage.transfers import TransferStore
from server.manager.transfers.models import NewTransfer, TransferOperation


def _store_with_message(tmp_path) -> TransferStore:
    store = TransferStore(tmp_path / "transfers.sqlite", server_id="public-b2")
    store.create(
        NewTransfer(
            idempotency_key="outbox-lease",
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
            expected_sha256="",
            expires_at=200.0,
        ),
        dispatch_to="public-b1",
        now=100.0,
    )
    return store


def test_outbox_lease_prevents_two_dispatchers_claiming_same_message(
    tmp_path,
) -> None:
    store = _store_with_message(tmp_path)

    first = store.claim_outbox(
        claimant="dispatcher-a", lease_seconds=10, now=101.0,
    )
    concurrent = store.claim_outbox(
        claimant="dispatcher-b", lease_seconds=10, now=105.0,
    )

    assert len(first) == 1
    assert concurrent == []
    assert first[0].attempt == 1


def test_expired_outbox_lease_can_be_reclaimed_and_only_new_owner_can_ack(
    tmp_path,
) -> None:
    store = _store_with_message(tmp_path)
    first = store.claim_outbox(
        claimant="dispatcher-a", lease_seconds=10, now=101.0,
    )[0]
    reclaimed = store.claim_outbox(
        claimant="dispatcher-b", lease_seconds=10, now=112.0,
    )[0]

    assert reclaimed.outbox_id == first.outbox_id
    assert reclaimed.attempt == 2
    with pytest.raises(RuntimeError, match="lease owner"):
        store.acknowledge_outbox(
            reclaimed.outbox_id, claimant="dispatcher-a", now=113.0,
        )

    store.acknowledge_outbox(
        reclaimed.outbox_id, claimant="dispatcher-b", now=114.0,
    )
    store.acknowledge_outbox(
        reclaimed.outbox_id, claimant="dispatcher-b", now=115.0,
    )

    assert store.claim_outbox(claimant="dispatcher-c", now=116.0) == []
