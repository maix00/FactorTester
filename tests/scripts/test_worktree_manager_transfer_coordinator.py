from __future__ import annotations

import hashlib

from server.manager.storage.transfers import (
    TransferAttemptStore,
    TransferStore,
    TransferTicketStore,
)
from server.manager.transfers.coordinator import (
    DownloadRequest,
    TransferCoordinator,
    UploadRequest,
)
from server.manager.transfers.models import TransferMode, TransferTicketRole
from server.manager.transfers.planner import NodeEndpoint


def _node(node_id: str, octet: int) -> NodeEndpoint:
    return NodeEndpoint(
        server_id=node_id,
        peer_data_endpoint=f"http://10.77.0.{octet}:17997",
        peer_control_endpoint=f"http://10.77.0.{octet}:17998",
        observed_at=1.0,
        expires_at=4_000_000_000.0,
        online=True,
    )


def _coordinator(tmp_path) -> TransferCoordinator:
    path = tmp_path / "transfers.sqlite"
    peer = _PeerGateway()
    return TransferCoordinator(
        manager_id="node-b",
        client_data_endpoint="https://factor.example:7997",
        requests=TransferStore(path, server_id="node-b"),
        attempts=TransferAttemptStore(path, server_id="node-b"),
        tickets=TransferTicketStore(path, server_id="node-b"),
        peer_gateway=peer,
    )


class _PeerGateway:
    def __init__(self) -> None:
        self.imported: list[tuple[str, str]] = []

    def import_context(self, transfer, attempt) -> None:
        self.imported.append((transfer.transfer_id, attempt.attempt_id))


def _download() -> DownloadRequest:
    raw = b"abcdef"
    return DownloadRequest(
        idempotency_key="download-1",
        principal="alice",
        storage_server_id="node-a",
        job_id="job-1",
        artifact_name="result.bin",
        expected_size=len(raw),
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        expires_at=4_000_000_000.0,
    )


def test_download_freezes_private_route_but_returns_only_public_access(tmp_path) -> None:
    coordinator = _coordinator(tmp_path)
    access = coordinator.prepare_download(
        _download(),
        endpoints={"node-a": _node("node-a", 1), "node-b": _node("node-b", 2)},
        now=100.0,
    )

    attempt = coordinator.attempts.require(access.attempt_id)
    assert access.mode is TransferMode.DIRECT_PULL
    assert access.data_endpoint == "https://factor.example:7997"
    assert access.path.endswith("/download")
    assert "10.77.0" not in repr(access)
    assert attempt.routes.source_peer_data_endpoint == "http://10.77.0.1:17997"
    assert coordinator.peer_gateway.imported == [
        (access.transfer_id, access.attempt_id),
    ]
    coordinator.tickets.verify(
        access.bearer,
        required_role=TransferTicketRole.CLIENT_DOWNLOAD,
        attempt_id=access.attempt_id,
        node_id="",
        start_offset=0,
        end_offset=6,
        now=101.0,
    )


def test_upload_uses_direct_push_and_one_use_client_ticket(tmp_path) -> None:
    coordinator = _coordinator(tmp_path)
    request = UploadRequest(
        idempotency_key="upload-1",
        principal="alice",
        storage_server_id="node-a",
        job_id="job-1",
        artifact_name="source.py",
        expected_size=6,
        expected_sha256=hashlib.sha256(b"abcdef").hexdigest(),
        expires_at=4_000_000_000.0,
    )

    access = coordinator.prepare_upload(
        request,
        endpoints={"node-a": _node("node-a", 1), "node-b": _node("node-b", 2)},
        now=100.0,
    )

    assert access.mode is TransferMode.DIRECT_PUSH
    assert access.path.endswith("/upload")
    assert coordinator.peer_gateway.imported == [
        (access.transfer_id, access.attempt_id),
    ]
    grant = coordinator.tickets.verify(
        access.bearer,
        required_role=TransferTicketRole.CLIENT_UPLOAD,
        attempt_id=access.attempt_id,
        node_id="",
        start_offset=0,
        end_offset=6,
        consume=True,
        now=101.0,
    )
    assert grant.max_uses == 1


def test_idempotent_retry_reuses_attempt_but_rotates_ticket(tmp_path) -> None:
    coordinator = _coordinator(tmp_path)
    endpoints = {"node-a": _node("node-a", 1), "node-b": _node("node-b", 2)}
    first = coordinator.prepare_download(_download(), endpoints=endpoints, now=100.0)
    retry = coordinator.prepare_download(_download(), endpoints=endpoints, now=101.0)

    assert retry.transfer_id == first.transfer_id
    assert retry.attempt_id == first.attempt_id
    assert retry.bearer != first.bearer
    assert coordinator.peer_gateway.imported == [
        (first.transfer_id, first.attempt_id),
        (retry.transfer_id, retry.attempt_id),
    ]
