from __future__ import annotations

import hashlib
import threading
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from urllib.request import Request, urlopen

from server.manager.data_plane.server import (
    ClientDataPlaneHTTPServer,
    DataPlaneRuntime,
    PeerDataPlaneHTTPServer,
)
from server.manager.storage.transfers import (
    TransferAttemptStore,
    TransferReplicaStore,
    TransferStore,
    TransferTicketStore,
)
from server.manager.transfers.models import (
    AttemptRouteSnapshot,
    NewTransfer,
    NewTransferAttempt,
    TransferMode,
    TransferOperation,
    TransferStatus,
    TransferTicketRole,
)


@contextmanager
def _data_plane(runtime: DataPlaneRuntime, *, peer: bool = False):
    server_type = PeerDataPlaneHTTPServer if peer else ClientDataPlaneHTTPServer
    server = server_type(("127.0.0.1", 0), runtime=runtime)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _direct_push_context(path: Path, raw: bytes):
    requests = TransferStore(path, server_id="selected-manager")
    transfer = requests.create(
        NewTransfer(
            idempotency_key="wireguard-direct-upload",
            operation=TransferOperation.UPLOAD,
            principal="alice",
            request_owner_manager_id="selected-manager",
            source_server_id="selected-manager",
            destination_server_id="storage-node",
            storage_server_id="storage-node",
            job_id="job-1",
            artifact_name="source.py",
            expected_size=len(raw),
            expected_sha256=hashlib.sha256(raw).hexdigest(),
            expires_at=4_000_000_000.0,
        ),
    )
    transfer = requests.transition(
        transfer.transfer_id,
        TransferStatus.PLANNED,
        expected=TransferStatus.CREATED,
    )
    attempt = TransferAttemptStore(
        path, server_id="selected-manager",
    ).begin(
        NewTransferAttempt(
            attempt_key=f"{transfer.transfer_id}:1",
            transfer_id=transfer.transfer_id,
            mode=TransferMode.DIRECT_PUSH,
            request_owner_manager_id="selected-manager",
            source_server_id="selected-manager",
            destination_server_id="storage-node",
            resume_offset=0,
            expires_at=transfer.expires_at,
            routes=AttemptRouteSnapshot(
                client_data_endpoint="http://client-placeholder:7997",
                source_peer_data_endpoint="http://source-placeholder:17997",
                source_peer_control_endpoint="http://source-placeholder:17998",
                destination_peer_data_endpoint="http://destination-placeholder:17997",
                destination_peer_control_endpoint="http://destination-placeholder:17998",
            ),
        )
    )
    return requests.require(transfer.transfer_id), attempt


def test_client_upload_streams_to_wireguard_destination_without_relay_copy(
    tmp_path,
) -> None:
    raw = b"class UploadedFactor:\n    pass\n"
    requester_db = tmp_path / "requester.sqlite"
    destination_db = tmp_path / "destination.sqlite"
    transfer, attempt = _direct_push_context(requester_db, raw)
    TransferReplicaStore(
        destination_db, server_id="storage-node",
    ).import_context(transfer, attempt)

    destination_runtime = DataPlaneRuntime(
        server_id="storage-node",
        transfer_database=destination_db,
        staging_root=tmp_path / "destination-staging",
        origin_resolver=lambda _transfer: Path("/not-an-origin"),
    )
    destination_bearer = destination_runtime.tickets.issue(
        transfer_id=transfer.transfer_id,
        attempt_id=attempt.attempt_id,
        role=TransferTicketRole.DESTINATION_WRITE,
        principal=transfer.principal,
        node_id="selected-manager",
        start_offset=0,
        end_offset=len(raw),
        expires_at=transfer.expires_at,
        max_uses=1,
    ).bearer

    with _data_plane(destination_runtime, peer=True) as destination_endpoint:
        attempt = replace(
            attempt,
            routes=replace(
                attempt.routes,
                destination_peer_data_endpoint=destination_endpoint,
            ),
        )
        # Freeze the discovered test endpoint exactly as production planning does.
        with destination_runtime.attempts._connect() as connection:
            connection.execute(
                "UPDATE transfer_attempts SET destination_peer_data_endpoint=? "
                "WHERE attempt_id=?",
                (destination_endpoint, attempt.attempt_id),
            )
        with TransferAttemptStore(
            requester_db, server_id="selected-manager"
        )._connect() as connection:
            connection.execute(
                "UPDATE transfer_attempts SET destination_peer_data_endpoint=? "
                "WHERE attempt_id=?",
                (destination_endpoint, attempt.attempt_id),
            )
        requester_runtime = DataPlaneRuntime(
            server_id="selected-manager",
            transfer_database=requester_db,
            staging_root=tmp_path / "requester-staging",
            origin_resolver=lambda _transfer: Path("/not-an-origin"),
            destination_ticket_provider=lambda _context: destination_bearer,
            destination_endpoint_provider=(
                lambda _context: destination_endpoint
            ),
        )
        client_bearer = requester_runtime.tickets.issue(
            transfer_id=transfer.transfer_id,
            attempt_id=attempt.attempt_id,
            role=TransferTicketRole.CLIENT_UPLOAD,
            principal=transfer.principal,
            node_id="",
            start_offset=0,
            end_offset=len(raw),
            expires_at=transfer.expires_at,
            max_uses=1,
        ).bearer
        with _data_plane(requester_runtime) as client_endpoint:
            request = Request(
                client_endpoint
                + f"/v1/transfers/{attempt.attempt_id}/upload",
                data=raw,
                headers={
                    "Authorization": f"Bearer {client_bearer}",
                    "Content-Type": "application/octet-stream",
                },
                method="PUT",
            )
            with urlopen(request, timeout=2) as response:
                assert response.status == 201

    destination = destination_runtime.destination_path(transfer, attempt)
    assert destination.read_bytes() == raw
    assert not any((tmp_path / "requester-staging").rglob("*"))
