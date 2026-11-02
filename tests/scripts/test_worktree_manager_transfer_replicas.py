from __future__ import annotations

from dataclasses import replace
import sqlite3
from types import SimpleNamespace

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
from server.manager.transfers.wire import parse_transfer_context, transfer_context_payload


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


def test_stable_user_identity_is_signed_replicated_and_part_of_immutable_context(tmp_path):
    transfer, attempt = _direct_context(tmp_path)
    transfer = replace(transfer, principal_identity_id="stable-identity-a")
    payload = transfer_context_payload(transfer, attempt)
    assert payload["schema_version"] == 2
    decoded, decoded_attempt = parse_transfer_context(payload)
    assert decoded.principal_identity_id == "stable-identity-a"
    source = TransferReplicaStore(tmp_path / "source.sqlite", server_id="node-a")
    assert source.import_context(decoded, decoded_attempt, now=101)[0].principal_identity_id == "stable-identity-a"
    with pytest.raises(ValueError, match="replica conflicts"):
        source.import_context(replace(decoded, principal_identity_id="other"), decoded_attempt, now=102)
    payload["schema_version"] = 1
    with pytest.raises(ValueError, match="cannot claim"):
        parse_transfer_context(payload)
    payload["schema_version"] = 2
    payload["transfer"]["principal_identity_id"] = ""
    with pytest.raises(ValueError, match="stable identity"):
        parse_transfer_context(payload)


def test_v9_transfer_schema_upgrade_preserves_existing_records(tmp_path):
    transfer, _attempt = _direct_context(tmp_path)
    path = tmp_path / "requester.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE transfer_requests DROP COLUMN principal_identity_id")
        db.execute("UPDATE transfer_meta SET value='9' WHERE key='schema_version'")
    upgraded = TransferStore(path, server_id="node-b")
    record = upgraded.require(transfer.transfer_id)
    assert record.principal_identity_id == "" and record.principal == transfer.principal
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM transfer_meta WHERE key='schema_version'").fetchone()[0] == "10"


def test_data_plane_rejects_ticket_if_bound_to_another_transfer_or_principal():
    from server.manager.data_plane.authorization import authorize
    grant = SimpleNamespace(transfer_id="transfer", principal="other")
    runtime = SimpleNamespace(tickets=SimpleNamespace(verify=lambda *_a, **_k: grant),
                              authorize_transfer_telemetry=lambda _h: None)
    handler = SimpleNamespace(headers={"Authorization": "Bearer capability"})
    context = SimpleNamespace(transfer=SimpleNamespace(transfer_id="transfer", principal="alice"),
                              attempt=SimpleNamespace(attempt_id="attempt", resume_offset=0, expected_size=6))
    with pytest.raises(PermissionError, match="identity"):
        authorize(handler, runtime, context, role=TransferTicketRole.CLIENT_DOWNLOAD)
    grant.principal, grant.transfer_id = "alice", "another-transfer"
    with pytest.raises(PermissionError, match="identity"):
        authorize(handler, runtime, context, role=TransferTicketRole.CLIENT_DOWNLOAD)
