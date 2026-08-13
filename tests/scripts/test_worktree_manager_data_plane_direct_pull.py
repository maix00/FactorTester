from __future__ import annotations

import hashlib
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from server.manager import runtime as manager
from server.manager.data_plane.server import DataPlaneHTTPServer, DataPlaneRuntime
from server.manager.storage.transfers import (
    TransferAttemptStore,
    TransferStore,
    TransferTicketStore,
)
from server.manager.transfers.coordinator import DownloadRequest, TransferCoordinator
from server.manager.transfers.node_client import NodeControlClient
from server.manager.transfers.node_keys import NodeKey
from server.manager.transfers.planner import NodeReachability
from server.manager.transfers.wire import transfer_context_payload


@contextmanager
def _manager(state):
    manager.Handler.state = state
    server = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@contextmanager
def _data_plane(runtime):
    server = DataPlaneHTTPServer(("127.0.0.1", 0), runtime=runtime)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_direct_pull_streams_public_origin_through_selected_manager_7997(
    tmp_path,
) -> None:
    raw = b"public-to-public-artifact"
    source_state = manager.ManagerState(
        tmp_path / "source-manager", "python", server_id="public-b1",
    )
    source_state.federation_registration_token = "enroll-secret"
    source_file = tmp_path / "source.bin"
    source_file.write_bytes(raw)
    requester_db = tmp_path / "requester.sqlite"
    requester_key = NodeKey.load_or_create(
        tmp_path / "public-b2.key", node_id="public-b2",
    )
    coordinator = TransferCoordinator(
        manager_id="public-b2",
        data_endpoint="http://placeholder:7997",
        requests=TransferStore(requester_db, server_id="public-b2"),
        attempts=TransferAttemptStore(requester_db, server_id="public-b2"),
        tickets=TransferTicketStore(requester_db, server_id="public-b2"),
    )
    now = time.time()

    with _manager(source_state) as source_manager:
        peer_client = NodeControlClient(
            source_manager,
            key=requester_key,
            enrollment_token="enroll-secret",
        )
        peer_client.enroll()
        access = coordinator.prepare_download(
            DownloadRequest(
                idempotency_key="direct-pull-http",
                principal="alice",
                storage_server_id="public-b1",
                job_id="job-1",
                artifact_name="result.bin",
                expected_size=len(raw),
                expected_sha256=hashlib.sha256(raw).hexdigest(),
                expires_at=now + 600,
            ),
            observations={
                "public-b1": NodeReachability(
                    server_id="public-b1",
                    data_endpoint="http://source-placeholder:7997",
                    reachable_from=frozenset({"public-b2"}),
                    connection_owner_manager_id="public-b1",
                    observed_at=now,
                    expires_at=now + 60,
                    online=True,
                ),
                "public-b2": NodeReachability(
                    server_id="public-b2",
                    data_endpoint="http://requester-placeholder:7997",
                    reachable_from=frozenset({"public-b2"}),
                    connection_owner_manager_id="public-b2",
                    observed_at=now,
                    expires_at=now + 60,
                    online=True,
                ),
            },
            now=now,
        )
        transfer = coordinator.requests.require(access.transfer_id)
        attempt = coordinator.attempts.require(access.attempt_id)
        peer_client.signed_json(
            "/api/federation/transfers/context",
            transfer_context_payload(transfer, attempt),
        )
        source_runtime = DataPlaneRuntime(
            server_id="public-b1",
            transfer_database=source_state.transfer_database_path,
            staging_root=tmp_path / "source-staging",
            origin_resolver=lambda _transfer: source_file,
        )
        with _data_plane(source_runtime) as source_data:
            requester_runtime = DataPlaneRuntime(
                server_id="public-b2",
                transfer_database=requester_db,
                staging_root=tmp_path / "requester-staging",
                origin_resolver=lambda _transfer: Path("/not-local"),
                origin_ticket_provider=lambda _context: (
                    peer_client.signed_json(
                        "/api/federation/transfers/origin-ticket",
                        {"attempt_id": attempt.attempt_id},
                    )["bearer"]
                ),
                source_endpoint_provider=lambda _context: source_data,
            )
            with _data_plane(requester_runtime) as requester_data:
                request = Request(
                    requester_data + access.path,
                    headers={
                        "Authorization": f"Bearer {access.bearer}",
                        "Range": "bytes=7-15",
                    },
                )
                with urlopen(request, timeout=2) as response:
                    received = response.read()
                    status = response.status
                    content_range = response.headers["Content-Range"]

    assert status == 206
    assert received == raw[7:16]
    assert content_range == f"bytes 7-15/{len(raw)}"
    assert list((tmp_path / "requester-staging").rglob("*")) == []


def test_direct_pull_forwards_unsatisfied_range_without_dropping_connection(
    tmp_path,
) -> None:
    raw = b"short"
    source_state = manager.ManagerState(
        tmp_path / "source-manager", "python", server_id="public-b1",
    )
    source_state.federation_registration_token = "enroll-secret"
    source_file = tmp_path / "source.bin"
    source_file.write_bytes(raw)
    requester_db = tmp_path / "requester.sqlite"
    requester_key = NodeKey.load_or_create(
        tmp_path / "public-b2.key", node_id="public-b2",
    )
    coordinator = TransferCoordinator(
        manager_id="public-b2",
        data_endpoint="http://placeholder:7997",
        requests=TransferStore(requester_db, server_id="public-b2"),
        attempts=TransferAttemptStore(requester_db, server_id="public-b2"),
        tickets=TransferTicketStore(requester_db, server_id="public-b2"),
    )
    now = time.time()

    with _manager(source_state) as source_manager:
        peer_client = NodeControlClient(
            source_manager,
            key=requester_key,
            enrollment_token="enroll-secret",
        )
        peer_client.enroll()
        access = coordinator.prepare_download(
            DownloadRequest(
                idempotency_key="direct-pull-invalid-range",
                principal="alice",
                storage_server_id="public-b1",
                job_id="job-1",
                artifact_name="result.bin",
                expected_size=len(raw),
                expected_sha256=hashlib.sha256(raw).hexdigest(),
                expires_at=now + 600,
            ),
            observations={
                "public-b1": NodeReachability(
                    server_id="public-b1",
                    data_endpoint="http://source-placeholder:7997",
                    reachable_from=frozenset({"public-b2"}),
                    connection_owner_manager_id="public-b1",
                    observed_at=now,
                    expires_at=now + 60,
                    online=True,
                ),
                "public-b2": NodeReachability(
                    server_id="public-b2",
                    data_endpoint="http://requester-placeholder:7997",
                    reachable_from=frozenset({"public-b2"}),
                    connection_owner_manager_id="public-b2",
                    observed_at=now,
                    expires_at=now + 60,
                    online=True,
                ),
            },
            now=now,
        )
        transfer = coordinator.requests.require(access.transfer_id)
        attempt = coordinator.attempts.require(access.attempt_id)
        peer_client.signed_json(
            "/api/federation/transfers/context",
            transfer_context_payload(transfer, attempt),
        )
        source_runtime = DataPlaneRuntime(
            server_id="public-b1",
            transfer_database=source_state.transfer_database_path,
            staging_root=tmp_path / "source-staging",
            origin_resolver=lambda _transfer: source_file,
        )
        with _data_plane(source_runtime) as source_data:
            requester_runtime = DataPlaneRuntime(
                server_id="public-b2",
                transfer_database=requester_db,
                staging_root=tmp_path / "requester-staging",
                origin_resolver=lambda _transfer: Path("/not-local"),
                origin_ticket_provider=lambda _context: (
                    peer_client.signed_json(
                        "/api/federation/transfers/origin-ticket",
                        {"attempt_id": attempt.attempt_id},
                    )["bearer"]
                ),
                source_endpoint_provider=lambda _context: source_data,
            )
            with _data_plane(requester_runtime) as requester_data:
                request = Request(
                    requester_data + access.path,
                    headers={
                        "Authorization": f"Bearer {access.bearer}",
                        "Range": "bytes=99-100",
                    },
                )
                with pytest.raises(HTTPError) as denied:
                    urlopen(request, timeout=2)

    assert denied.value.code == 416
    assert denied.value.headers["Content-Range"] == f"bytes */{len(raw)}"
