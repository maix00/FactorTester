from __future__ import annotations

import hashlib
import threading
from contextlib import contextmanager

import pytest
from urllib.error import HTTPError, URLError

from server.manager import runtime as manager
from server.manager.data_plane.staging import partial_path
from server.manager.http.peer_handler import peer_control_handler
from server.manager.storage.transfers import TransferReplicaStore
from server.manager.transfers.coordinator import (
    DownloadRequest,
    TransferCoordinator,
    UploadRequest,
)
from server.manager.transfers.node_client import NodeControlClient
from server.manager.transfers.node_keys import NodeKey
from server.manager.transfers.peer_gateway import TransferPeerGateway
from server.manager.transfers.planner import NodeEndpoint, NodeUnavailable
from server.manager.storage.transfers import (
    TransferAttemptStore,
    TransferStore,
    TransferTicketStore,
)
from server.manager.transfers.wire import transfer_context_payload


class _NoopPeerGateway:
    @staticmethod
    def import_context(_transfer, _attempt) -> None:
        pass


class _UnavailableTransport:
    def open(self, _request, *, timeout: float):
        del timeout
        raise URLError("connection refused")


@contextmanager
def _running_peer(state):
    server = manager.ThreadingHTTPServer(
        ("127.0.0.1", 0), peer_control_handler(state),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _node(node_id: str, octet: int) -> NodeEndpoint:
    return NodeEndpoint(
        server_id=node_id,
        peer_data_endpoint=f"http://10.77.0.{octet}:17997",
        peer_control_endpoint=f"http://10.77.0.{octet}:17998",
        observed_at=1.0,
        expires_at=4_000_000_000.0,
        online=True,
    )


def _context(tmp_path, *, operation: str):
    path = tmp_path / f"requester-{operation}.sqlite"
    coordinator = TransferCoordinator(
        manager_id="public-b2",
        client_data_endpoint="http://public-b2:7997",
        requests=TransferStore(path, server_id="public-b2"),
        attempts=TransferAttemptStore(path, server_id="public-b2"),
        tickets=TransferTicketStore(path, server_id="public-b2"),
        peer_gateway=_NoopPeerGateway(),
    )
    values = {
        "idempotency_key": f"peer-http-{operation}",
        "principal": "alice",
        "storage_server_id": "storage-b1",
        "job_id": "job-1",
        "artifact_name": "result.bin",
        "expected_size": 6,
        "expected_sha256": hashlib.sha256(b"abcdef").hexdigest(),
        "expires_at": 4_000_000_000.0,
    }
    endpoints = {
        "storage-b1": _node("storage-b1", 1),
        "public-b2": _node("public-b2", 2),
    }
    if operation == "download":
        access = coordinator.prepare_download(
            DownloadRequest(**values), endpoints=endpoints, now=100.0,
        )
    else:
        access = coordinator.prepare_upload(
            UploadRequest(**values), endpoints=endpoints, now=100.0,
        )
    return (
        coordinator.requests.require(access.transfer_id),
        coordinator.attempts.require(access.attempt_id),
    )


def _client(tmp_path, endpoint: str, *, node_id: str) -> NodeControlClient:
    client = NodeControlClient(
        endpoint,
        key=NodeKey.load_or_create(
            tmp_path / f"{node_id}.key", node_id=node_id,
        ),
        enrollment_token="enroll-secret",
    )
    client.enroll()
    return client


def test_signed_peer_imports_context_then_obtains_origin_ticket(tmp_path) -> None:
    source = manager.ManagerState(
        tmp_path / "source", "python", server_id="storage-b1",
        state_root=tmp_path / "source-state",
    )
    source.federation_registration_token = "enroll-secret"
    transfer, attempt = _context(tmp_path, operation="download")

    with _running_peer(source) as endpoint:
        client = _client(tmp_path, endpoint, node_id="public-b2")
        imported = client.signed_json(
            "/api/federation/transfers/context",
            transfer_context_payload(transfer, attempt),
        )
        issued = client.signed_json(
            "/api/federation/transfers/origin-ticket",
            {"attempt_id": attempt.attempt_id},
        )

    assert imported["attempt_id"] == attempt.attempt_id
    assert issued["role"] == "origin_read"
    assert issued["node_id"] == "public-b2"
    restored = TransferReplicaStore(
        source.transfer_database_path, server_id="storage-b1",
    ).require_context(attempt.attempt_id)
    assert restored == (transfer, attempt)


def test_peer_gateway_reports_offline_node_for_control_transport_failure(
    tmp_path,
) -> None:
    transfer, attempt = _context(tmp_path, operation="download")
    gateway = TransferPeerGateway(
        key=NodeKey.load_or_create(tmp_path / "requester.key", node_id="public-b2"),
        transport=_UnavailableTransport(),
    )

    with pytest.raises(NodeUnavailable) as denied:
        gateway.import_context(transfer, attempt)

    assert denied.value.code == "node_unreachable"
    assert denied.value.server_id == "storage-b1"
    assert "offline or unreachable" in str(denied.value)


def test_origin_ticket_uses_signed_identity_not_claimed_requester(tmp_path) -> None:
    source = manager.ManagerState(
        tmp_path / "source", "python", server_id="storage-b1",
        state_root=tmp_path / "source-state",
    )
    source.federation_registration_token = "enroll-secret"
    transfer, attempt = _context(tmp_path, operation="download")

    with _running_peer(source) as endpoint:
        legitimate = _client(tmp_path, endpoint, node_id="public-b2")
        legitimate.signed_json(
            "/api/federation/transfers/context",
            transfer_context_payload(transfer, attempt),
        )
        attacker = _client(tmp_path, endpoint, node_id="public-b3")
        with pytest.raises(HTTPError) as denied:
            attacker.signed_json(
                "/api/federation/transfers/origin-ticket",
                {
                    "attempt_id": attempt.attempt_id,
                    "requester_server_id": "public-b2",
                },
            )

    assert denied.value.code == 403


def test_destination_reports_only_durable_private_resume_offset(tmp_path) -> None:
    destination = manager.ManagerState(
        tmp_path / "destination", "python", server_id="storage-b1",
        data_root=tmp_path / "data",
        state_root=tmp_path / "destination-state",
    )
    destination.federation_registration_token = "enroll-secret"
    transfer, attempt = _context(tmp_path, operation="upload")

    with _running_peer(destination) as endpoint:
        client = _client(tmp_path, endpoint, node_id="public-b2")
        client.signed_json(
            "/api/federation/transfers/context",
            transfer_context_payload(transfer, attempt),
        )
        partial = partial_path(destination.transfer_submission_root, transfer)
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(b"abc")
        value = client.signed_json(
            "/api/federation/transfers/resume-offset",
            {"attempt_id": attempt.attempt_id},
        )

    assert value["resume_offset"] == 3
    assert value["completed"] is False
    assert value["storage_reference"] == ""
