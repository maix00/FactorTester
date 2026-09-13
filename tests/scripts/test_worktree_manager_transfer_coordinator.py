from __future__ import annotations

import hashlib

import pytest

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
from server.manager.transfers.models import (
    AttemptStatus,
    TransferMode,
    TransferStatus,
    TransferTicketRole,
)
from server.manager.transfers.planner import NodeEndpoint, NodeUnavailable


def _node(node_id: str, octet: int) -> NodeEndpoint:
    return NodeEndpoint(
        server_id=node_id,
        peer_data_endpoint=f"http://10.77.0.{octet}:17997",
        peer_control_endpoint=f"http://10.77.0.{octet}:17998",
        observed_at=1.0,
        expires_at=4_000_000_000.0,
        online=True,
    )


def _coordinator(tmp_path, *, peer=None) -> TransferCoordinator:
    path = tmp_path / "transfers.sqlite"
    peer = _PeerGateway() if peer is None else peer
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
        self.resume_value = 0

    def import_context(self, transfer, attempt) -> None:
        self.imported.append((transfer.transfer_id, attempt.attempt_id))

    def resume_offset(self, _transfer, _attempt) -> int:
        return self.resume_value


class _OfflinePeerGateway(_PeerGateway):
    def __init__(self) -> None:
        super().__init__()
        self.transfer_id = ""

    def import_context(self, _transfer, _attempt) -> None:
        self.transfer_id = _transfer.transfer_id
        raise ConnectionError("connection refused")


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


def test_peer_unavailable_fails_transfer_without_retry(tmp_path) -> None:
    peer = _OfflinePeerGateway()
    coordinator = _coordinator(tmp_path, peer=peer)

    with pytest.raises(NodeUnavailable) as denied:
        coordinator.prepare_download(
            _download(),
            endpoints={"node-a": _node("node-a", 1), "node-b": _node("node-b", 2)},
            now=100.0,
        )

    assert denied.value.code == "node_unreachable"
    assert denied.value.server_id == "node-a"
    transfer = coordinator.requests.require(peer.transfer_id)
    attempt = coordinator.attempts.latest(transfer.transfer_id)
    assert transfer.status is TransferStatus.FAILED
    assert attempt is not None
    assert attempt.status is AttemptStatus.FAILED
    assert "connection refused" in attempt.last_error


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


def test_upload_retry_accepts_completed_destination_as_zero_byte_attempt(
    tmp_path,
) -> None:
    coordinator = _coordinator(tmp_path)
    endpoints = {"node-a": _node("node-a", 1), "node-b": _node("node-b", 2)}
    request = UploadRequest(
        idempotency_key="upload-response-lost",
        principal="alice",
        storage_server_id="node-a",
        job_id="job-1",
        artifact_name="source.py",
        expected_size=6,
        expected_sha256=hashlib.sha256(b"abcdef").hexdigest(),
        expires_at=4_000_000_000.0,
    )
    first = coordinator.prepare_upload(request, endpoints=endpoints, now=100.0)
    coordinator.attempts.transition(
        first.attempt_id, "failed", now=101.0, error="response lost",
    )
    coordinator.requests.transition(
        first.transfer_id, "retry_wait", expected="dispatched", now=101.0,
    )
    coordinator.peer_gateway.resume_value = 6

    retry = coordinator.prepare_upload(request, endpoints=endpoints, now=102.0)

    assert retry.transfer_id == first.transfer_id
    assert retry.attempt_id != first.attempt_id
    assert retry.resume_offset == retry.expected_size == 6
    coordinator.tickets.verify(
        retry.bearer,
        required_role=TransferTicketRole.CLIENT_UPLOAD,
        attempt_id=retry.attempt_id,
        node_id="",
        start_offset=6,
        end_offset=6,
        consume=True,
        now=103.0,
    )


def test_download_keys_are_scoped_to_requesting_manager_and_principal(tmp_path):
    from dataclasses import replace
    coordinator = _coordinator(tmp_path)
    endpoints = {'node-a': _node('node-a', 1), 'node-b': _node('node-b', 2),
                 'node-c': _node('node-c', 3)}
    first = coordinator.prepare_download(_download(), endpoints=endpoints, now=100)
    retry = coordinator.prepare_download(_download(), endpoints=endpoints, now=101)
    assert first.transfer_id == retry.transfer_id
    other_user = coordinator.prepare_download(replace(_download(), principal='bob'),
                                               endpoints=endpoints, now=102)
    assert other_user.transfer_id != first.transfer_id
    # A receiving Manager already holds the first transfer's replicated row.
    # Its own request for the same bytes must not collide with that row.
    coordinator.manager_id = 'node-c'
    other_manager = coordinator.prepare_download(_download(), endpoints=endpoints, now=103)
    assert other_manager.transfer_id not in {first.transfer_id, other_user.transfer_id}
