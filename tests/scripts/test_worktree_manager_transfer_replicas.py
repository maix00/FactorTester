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
from server.manager.transfers.planner import NodeEndpoint


class _NoopPeerGateway:
    @staticmethod
    def import_context(_transfer, _attempt) -> None:
        pass


def _node(node_id: str, octet: int) -> NodeEndpoint:
    return NodeEndpoint(
        server_id=node_id,
        peer_data_endpoint=f"http://10.77.0.{octet}:17997",
        peer_control_endpoint=f"http://10.77.0.{octet}:17998",
        observed_at=1.0,
        expires_at=4_000_000_000.0,
        online=True,
    )


def _direct_context(tmp_path):
    requester_path = tmp_path / "requester.sqlite"
    coordinator = TransferCoordinator(
        manager_id="node-b",
        client_data_endpoint="https://factor.example:7997",
        requests=TransferStore(requester_path, server_id="node-b"),
        attempts=TransferAttemptStore(requester_path, server_id="node-b"),
        tickets=TransferTicketStore(requester_path, server_id="node-b"),
        peer_gateway=_NoopPeerGateway(),
    )
    access = coordinator.prepare_download(
        DownloadRequest(
            idempotency_key="direct-download",
            principal="alice",
            storage_server_id="node-a",
            job_id="job-1",
            artifact_name="result.bin",
            expected_size=6,
            expected_sha256="a" * 64,
            expires_at=4_000_000_000.0,
        ),
        endpoints={"node-a": _node("node-a", 1), "node-b": _node("node-b", 2)},
        now=100.0,
    )
    return (
        coordinator.requests.require(access.transfer_id),
        coordinator.attempts.require(access.attempt_id),
    )


def test_transfer_replica_preserves_ids_and_is_idempotent(tmp_path) -> None:
    transfer, attempt = _direct_context(tmp_path)
    source_path = tmp_path / "source.sqlite"
    replicas = TransferReplicaStore(source_path, server_id="node-a")

    first = replicas.import_context(transfer, attempt, now=101.0)
    duplicate = TransferReplicaStore(
        source_path, server_id="node-a",
    ).import_context(transfer, attempt, now=102.0)

    assert duplicate == first
    assert first[0].transfer_id == transfer.transfer_id
    assert first[1].attempt_id == attempt.attempt_id
    assert first[1].mode is TransferMode.DIRECT_PULL
    with pytest.raises(ValueError, match="replica conflicts"):
        replicas.import_context(
            replace(transfer, artifact_name="changed.bin"), attempt, now=103.0,
        )


def test_source_issues_origin_ticket_only_to_request_owner(tmp_path) -> None:
    transfer, attempt = _direct_context(tmp_path)
    source_path = tmp_path / "source.sqlite"
    replicas = TransferReplicaStore(source_path, server_id="node-a")
    replicas.import_context(transfer, attempt, now=101.0)
    tickets = TransferTicketStore(source_path, server_id="node-a")
    issuer = OriginTicketIssuer(
        manager_id="node-a", replicas=replicas, tickets=tickets,
    )

    issued = issuer.issue(
        attempt_id=attempt.attempt_id,
        requester_node_id="node-b",
        now=102.0,
    )

    tickets.verify(
        issued.bearer,
        required_role=TransferTicketRole.ORIGIN_READ,
        attempt_id=attempt.attempt_id,
        node_id="node-b",
        start_offset=0,
        end_offset=6,
        now=103.0,
    )
    with pytest.raises(PermissionError, match="request owner"):
        issuer.issue(
            attempt_id=attempt.attempt_id,
            requester_node_id="node-c",
            now=104.0,
        )


def test_replica_rejects_context_for_non_storage_server(tmp_path) -> None:
    transfer, attempt = _direct_context(tmp_path)
    replicas = TransferReplicaStore(
        tmp_path / "wrong-source.sqlite", server_id="node-c",
    )

    with pytest.raises(PermissionError, match="storage server"):
        replicas.import_context(transfer, attempt, now=101.0)
