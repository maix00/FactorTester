from __future__ import annotations

from dataclasses import replace

import pytest

from server.manager.storage.transfers import (
    TransferAttemptStore,
    TransferReplicaStore,
    TransferStore,
    TransferTicketStore,
)
from server.manager.transfers.coordinator import DownloadRequest, TransferCoordinator
from server.manager.transfers.models import TransferMode, TransferTicketRole
from server.manager.transfers.origin_tickets import OriginTicketIssuer
from server.manager.transfers.planner import NodeReachability


def _direct_context(tmp_path):
    requester_path = tmp_path / "requester.sqlite"
    coordinator = TransferCoordinator(
        manager_id="public-b2",
        data_endpoint="http://public-b2:7997",
        requests=TransferStore(requester_path, server_id="public-b2"),
        attempts=TransferAttemptStore(requester_path, server_id="public-b2"),
        tickets=TransferTicketStore(requester_path, server_id="public-b2"),
    )
    access = coordinator.prepare_download(
        DownloadRequest(
            idempotency_key="direct-download",
            principal="alice",
            storage_server_id="public-b1",
            job_id="job-1",
            artifact_name="result.bin",
            expected_size=6,
            expected_sha256="a" * 64,
            expires_at=4_000_000_000.0,
        ),
        observations={
            "public-b1": NodeReachability(
                server_id="public-b1",
                data_endpoint="http://public-b1:7997",
                reachable_from=frozenset({"public-b2"}),
                connection_owner_manager_id="public-b1",
                observed_at=1.0,
                expires_at=4_000_000_000.0,
                online=True,
            ),
            "public-b2": NodeReachability(
                server_id="public-b2",
                data_endpoint="http://public-b2:7997",
                reachable_from=frozenset({"public-b2"}),
                connection_owner_manager_id="public-b2",
                observed_at=1.0,
                expires_at=4_000_000_000.0,
                online=True,
            ),
        },
        now=100.0,
    )
    return (
        coordinator.requests.require(access.transfer_id),
        coordinator.attempts.require(access.attempt_id),
    )


def test_transfer_replica_preserves_ids_and_is_idempotent(tmp_path) -> None:
    transfer, attempt = _direct_context(tmp_path)
    source_path = tmp_path / "source.sqlite"
    replicas = TransferReplicaStore(source_path, server_id="public-b1")

    first = replicas.import_context(transfer, attempt, now=101.0)
    duplicate = TransferReplicaStore(
        source_path, server_id="public-b1",
    ).import_context(transfer, attempt, now=102.0)

    assert duplicate == first
    restored_transfer, restored_attempt = first
    assert restored_transfer.transfer_id == transfer.transfer_id
    assert restored_attempt.attempt_id == attempt.attempt_id
    assert restored_attempt.mode is TransferMode.DIRECT_PULL
    with pytest.raises(ValueError, match="replica conflicts"):
        replicas.import_context(
            replace(transfer, artifact_name="changed"), attempt, now=103.0,
        )


def test_source_issues_origin_ticket_only_to_request_owner(tmp_path) -> None:
    transfer, attempt = _direct_context(tmp_path)
    source_path = tmp_path / "source.sqlite"
    replicas = TransferReplicaStore(source_path, server_id="public-b1")
    replicas.import_context(transfer, attempt, now=101.0)
    tickets = TransferTicketStore(source_path, server_id="public-b1")
    issuer = OriginTicketIssuer(
        manager_id="public-b1",
        replicas=replicas,
        tickets=tickets,
    )

    issued = issuer.issue(
        attempt_id=attempt.attempt_id,
        requester_node_id="public-b2",
        now=102.0,
    )

    tickets.verify(
        issued.bearer,
        required_role=TransferTicketRole.ORIGIN_READ,
        attempt_id=attempt.attempt_id,
        node_id="public-b2",
        start_offset=0,
        end_offset=6,
        now=103.0,
    )
    with pytest.raises(PermissionError, match="request owner"):
        issuer.issue(
            attempt_id=attempt.attempt_id,
            requester_node_id="public-b3",
            now=104.0,
        )


def test_replica_rejects_context_for_another_source_server(tmp_path) -> None:
    transfer, attempt = _direct_context(tmp_path)
    replicas = TransferReplicaStore(
        tmp_path / "wrong-source.sqlite", server_id="public-b3",
    )

    with pytest.raises(PermissionError, match="source server"):
        replicas.import_context(transfer, attempt, now=101.0)
