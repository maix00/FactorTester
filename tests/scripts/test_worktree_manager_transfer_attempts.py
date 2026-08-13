from __future__ import annotations

from dataclasses import replace

import pytest

from server.manager.storage.transfers import TransferAttemptStore, TransferStore
from server.manager.transfers.models import (
    AttemptRouteSnapshot,
    AttemptStatus,
    NewTransfer,
    NewTransferAttempt,
    TransferMode,
    TransferOperation,
    TransferStatus,
)


def _planned_transfer(tmp_path):
    path = tmp_path / "transfers.sqlite"
    requests = TransferStore(path, server_id="node-b")
    transfer = requests.create(NewTransfer(
        idempotency_key="attempt-parent",
        operation=TransferOperation.DOWNLOAD,
        principal="alice",
        request_owner_manager_id="node-b",
        source_server_id="node-a",
        destination_server_id="node-b",
        storage_server_id="node-a",
        job_id="job-1",
        artifact_name="result.bin",
        expected_size=12,
        expected_sha256="a" * 64,
        expires_at=300.0,
    ), now=100.0)
    transfer = requests.transition(
        transfer.transfer_id, TransferStatus.PLANNED, now=101.0,
    )
    return path, requests, transfer


def _attempt(transfer, *, key: str = "attempt-parent:1", offset: int = 4):
    return NewTransferAttempt(
        attempt_key=key,
        transfer_id=transfer.transfer_id,
        mode=TransferMode.DIRECT_PULL,
        request_owner_manager_id="node-b",
        source_server_id="node-a",
        destination_server_id="node-b",
        resume_offset=offset,
        expires_at=220.0,
        routes=AttemptRouteSnapshot(
            client_data_endpoint="https://factor.example:7997",
            source_peer_data_endpoint="http://10.77.0.1:17997",
            source_peer_control_endpoint="http://10.77.0.1:17998",
            destination_peer_data_endpoint="http://10.77.0.2:17997",
            destination_peer_control_endpoint="http://10.77.0.2:17998",
        ),
    )


def test_attempt_topology_is_durable_idempotent_and_fixed(tmp_path) -> None:
    path, _requests, transfer = _planned_transfer(tmp_path)
    store = TransferAttemptStore(path, server_id="node-b")
    plan = _attempt(transfer)

    first = store.begin(plan, now=102.0)
    duplicate = TransferAttemptStore(path, server_id="node-b").begin(
        plan, now=103.0,
    )

    assert duplicate == first
    assert first.status is AttemptStatus.PLANNED
    assert first.routes.source_peer_data_endpoint == "http://10.77.0.1:17997"
    assert first.routes.client_data_endpoint == "https://factor.example:7997"
    with pytest.raises(ValueError, match="attempt key conflicts"):
        store.begin(replace(
            plan,
            routes=replace(
                plan.routes,
                source_peer_data_endpoint="http://10.77.0.3:17997",
            ),
        ), now=104.0)


def test_retry_requires_terminal_attempt_and_creates_new_ordinal(tmp_path) -> None:
    path, requests, transfer = _planned_transfer(tmp_path)
    store = TransferAttemptStore(path, server_id="node-b")
    first = store.begin(_attempt(transfer, offset=0), now=102.0)

    with pytest.raises(RuntimeError, match="active attempt"):
        store.begin(_attempt(
            transfer, key="attempt-parent:2", offset=4,
        ), now=103.0)

    store.transition(first.attempt_id, AttemptStatus.FAILED, now=104.0)
    requests.transition(transfer.transfer_id, TransferStatus.RETRY_WAIT, now=104.0)
    requests.transition(transfer.transfer_id, TransferStatus.PLANNED, now=105.0)
    second = store.begin(_attempt(
        transfer, key="attempt-parent:2", offset=4,
    ), now=106.0)

    assert second.ordinal == 2
    assert second.resume_offset == 4
    assert second.mode is TransferMode.DIRECT_PULL
