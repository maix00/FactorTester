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
)
from server.manager.transfers.models import (
    TransferMode,
    TransferStatus,
    TransferTicketRole,
)
from server.manager.transfers.planner import NodeReachability


def _coordinator(tmp_path) -> TransferCoordinator:
    path = tmp_path / "transfers.sqlite"
    return TransferCoordinator(
        manager_id="public-b2",
        data_endpoint="http://public-b2:7997",
        requests=TransferStore(path, server_id="public-b2"),
        attempts=TransferAttemptStore(path, server_id="public-b2"),
        tickets=TransferTicketStore(path, server_id="public-b2"),
    )


def _local_request() -> DownloadRequest:
    raw = b"abcdef"
    return DownloadRequest(
        idempotency_key="download-request-1",
        principal="alice",
        storage_server_id="public-b2",
        job_id="job-1",
        artifact_name="result.bin",
        expected_size=len(raw),
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        expires_at=4_000_000_000.0,
    )


def _local_observations() -> dict[str, NodeReachability]:
    return {
        "public-b2": NodeReachability(
            server_id="public-b2",
            data_endpoint="http://public-b2:7997",
            reachable_from=frozenset({"public-b2"}),
            connection_owner_manager_id="public-b2",
            observed_at=1.0,
            expires_at=4_000_000_000.0,
            online=True,
        ),
    }


def test_local_download_creates_fixed_attempt_and_client_consumer_ticket(
    tmp_path,
) -> None:
    coordinator = _coordinator(tmp_path)

    access = coordinator.prepare_download(
        _local_request(), observations=_local_observations(), now=100.0,
    )

    assert access.mode is TransferMode.LOCAL
    assert access.data_endpoint == "http://public-b2:7997"
    assert access.path.endswith(f"/{access.attempt_id}/consumer")
    transfer = coordinator.requests.require(access.transfer_id)
    attempt = coordinator.attempts.require(access.attempt_id)
    assert transfer.status is TransferStatus.DISPATCHED
    assert attempt.mode is TransferMode.LOCAL
    grant = coordinator.tickets.verify(
        access.bearer,
        required_role=TransferTicketRole.CONSUMER,
        attempt_id=access.attempt_id,
        node_id="",
        start_offset=0,
        end_offset=6,
        now=101.0,
    )
    assert grant.principal == "alice"


def test_retried_idempotency_key_reuses_request_and_attempt_but_rotates_ticket(
    tmp_path,
) -> None:
    coordinator = _coordinator(tmp_path)

    first = coordinator.prepare_download(
        _local_request(), observations=_local_observations(), now=100.0,
    )
    retry = coordinator.prepare_download(
        _local_request(), observations=_local_observations(), now=101.0,
    )

    assert retry.transfer_id == first.transfer_id
    assert retry.attempt_id == first.attempt_id
    assert retry.bearer != first.bearer


def test_client_ticket_expiry_never_exceeds_transfer_or_attempt(tmp_path) -> None:
    coordinator = _coordinator(tmp_path)
    request = _local_request()

    access = coordinator.prepare_download(
        request,
        observations=_local_observations(),
        now=request.expires_at - 10,
        ticket_ttl=60,
    )

    grant = coordinator.tickets.verify(
        access.bearer,
        required_role=TransferTicketRole.CONSUMER,
        attempt_id=access.attempt_id,
        node_id="",
        start_offset=0,
        end_offset=6,
        now=request.expires_at - 9,
    )
    assert grant.expires_at == request.expires_at
