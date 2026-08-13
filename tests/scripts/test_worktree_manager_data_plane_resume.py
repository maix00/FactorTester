from __future__ import annotations

import hashlib
import socket
import threading
import time
from contextlib import contextmanager
from urllib.request import Request, urlopen

from server.manager.data_plane.context import DataPlaneRuntime
from server.manager.data_plane.server import ClientDataPlaneHTTPServer
from server.manager.storage.transfers import (
    TransferAttemptStore,
    TransferStore,
    TransferTicketStore,
)
from server.manager.transfers.coordinator import TransferCoordinator, UploadRequest
from server.manager.transfers.models import AttemptStatus, TransferStatus


@contextmanager
def _running(runtime):
    server = ClientDataPlaneHTTPServer(("127.0.0.1", 0), runtime=runtime)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _wait_for_failure(coordinator, transfer_id: str, attempt_id: str) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        transfer = coordinator.requests.require(transfer_id)
        attempt = coordinator.attempts.require(attempt_id)
        if (
            transfer.status is TransferStatus.RETRY_WAIT
            and attempt.status is AttemptStatus.FAILED
        ):
            return
        time.sleep(0.01)
    raise AssertionError("interrupted upload did not enter retry state")


def test_interrupted_upload_resumes_from_durable_offset_with_new_attempt(
    tmp_path,
) -> None:
    raw = b"abcdef"
    database = tmp_path / "transfers.sqlite"
    runtime = DataPlaneRuntime(
        server_id="node-a",
        transfer_database=database,
        staging_root=tmp_path / "submissions",
        origin_resolver=lambda _transfer: tmp_path / "not-an-origin",
    )
    coordinator = TransferCoordinator(
        manager_id="node-a",
        client_data_endpoint="http://placeholder:7997",
        requests=TransferStore(database, server_id="node-a"),
        attempts=TransferAttemptStore(database, server_id="node-a"),
        tickets=TransferTicketStore(database, server_id="node-a"),
        local_resume_offset_provider=(
            lambda transfer, _attempt: runtime.resume_offset(transfer)
        ),
    )
    upload = UploadRequest(
        idempotency_key="resume-upload",
        principal="alice",
        storage_server_id="node-a",
        job_id="job-1",
        artifact_name="source.py",
        expected_size=len(raw),
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        expires_at=4_000_000_000.0,
    )

    first = coordinator.prepare_upload(upload, endpoints={}, now=time.time())
    with _running(runtime) as server:
        host, port = server.server_address
        connection = socket.create_connection((host, port), timeout=2)
        request = (
            f"PUT {first.path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Authorization: Bearer {first.bearer}\r\n"
            "Content-Type: application/octet-stream\r\n"
            "Content-Length: 6\r\n"
            "Connection: close\r\n\r\n"
        ).encode() + raw[:3]
        connection.sendall(request)
        connection.shutdown(socket.SHUT_WR)
        connection.close()
        _wait_for_failure(
            coordinator, first.transfer_id, first.attempt_id,
        )

        retry = coordinator.prepare_upload(
            upload, endpoints={}, now=time.time(),
        )
        assert retry.transfer_id == first.transfer_id
        assert retry.attempt_id != first.attempt_id
        assert retry.resume_offset == 3
        endpoint = f"http://{host}:{port}"
        with urlopen(Request(
            endpoint + retry.path,
            data=raw[retry.resume_offset:],
            method="PUT",
            headers={
                "Authorization": f"Bearer {retry.bearer}",
                "Content-Type": "application/octet-stream",
            },
        )) as response:
            assert response.status == 201

    transfer = coordinator.requests.require(first.transfer_id)
    attempt = coordinator.attempts.require(retry.attempt_id)
    destination = runtime.destination_path(transfer, attempt)
    assert destination.read_bytes() == raw
    assert transfer.status is TransferStatus.COMPLETED
    assert attempt.status is AttemptStatus.COMPLETED
    assert not destination.with_name(
        f".{destination.name}.transfer.tmp"
    ).exists()
