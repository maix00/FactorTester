from __future__ import annotations

import json
import threading
from contextlib import contextmanager

import pytest
from urllib.error import HTTPError

from server.manager import runtime as manager
from server.manager.storage.transfers import TransferReplicaStore
from server.manager.transfers.coordinator import DownloadRequest, TransferCoordinator
from server.manager.transfers.node_client import NodeControlClient
from server.manager.transfers.node_keys import NodeKey
from server.manager.transfers.planner import NodeReachability
from server.manager.storage.transfers import (
    TransferAttemptStore,
    TransferStore,
    TransferTicketStore,
)
from server.manager.transfers.wire import transfer_context_payload


@contextmanager
def _running(state):
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


def _context(tmp_path):
    path = tmp_path / "requester.sqlite"
    coordinator = TransferCoordinator(
        manager_id="public-b2",
        data_endpoint="http://public-b2:7997",
        requests=TransferStore(path, server_id="public-b2"),
        attempts=TransferAttemptStore(path, server_id="public-b2"),
        tickets=TransferTicketStore(path, server_id="public-b2"),
    )
    access = coordinator.prepare_download(
        DownloadRequest(
            idempotency_key="peer-http",
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


def test_signed_peer_imports_context_then_obtains_origin_ticket(tmp_path) -> None:
    source = manager.ManagerState(
        tmp_path / "source", "python", server_id="public-b1",
    )
    source.federation_registration_token = "enroll-secret"
    transfer, attempt = _context(tmp_path)
    requester_key = NodeKey.load_or_create(
        tmp_path / "public-b2.key", node_id="public-b2",
    )

    with _running(source) as endpoint:
        client = NodeControlClient(
            endpoint,
            key=requester_key,
            enrollment_token="enroll-secret",
        )
        client.enroll()
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
        source.transfer_database_path, server_id="public-b1",
    ).require_context(attempt.attempt_id)
    assert restored == (transfer, attempt)


def test_origin_ticket_uses_signed_identity_not_claimed_requester(tmp_path) -> None:
    source = manager.ManagerState(
        tmp_path / "source", "python", server_id="public-b1",
    )
    source.federation_registration_token = "enroll-secret"
    transfer, attempt = _context(tmp_path)
    attacker_key = NodeKey.load_or_create(
        tmp_path / "public-b3.key", node_id="public-b3",
    )

    with _running(source) as endpoint:
        legitimate = NodeControlClient(
            endpoint,
            key=NodeKey.load_or_create(
                tmp_path / "public-b2.key", node_id="public-b2",
            ),
            enrollment_token="enroll-secret",
        )
        legitimate.enroll()
        legitimate.signed_json(
            "/api/federation/transfers/context",
            transfer_context_payload(transfer, attempt),
        )
        attacker = NodeControlClient(
            endpoint,
            key=attacker_key,
            enrollment_token="enroll-secret",
        )
        attacker.enroll()
        with pytest.raises(HTTPError) as denied:
            attacker.signed_json(
                "/api/federation/transfers/origin-ticket",
                {
                    "attempt_id": attempt.attempt_id,
                    "requester_server_id": "public-b2",
                },
            )

    assert denied.value.code == 403
