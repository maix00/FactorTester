from __future__ import annotations

import hashlib
import threading
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from server.manager.data_plane.server import DataPlaneHTTPServer, DataPlaneRuntime
from server.manager.storage.transfers import (
    TransferAttemptStore,
    TransferStore,
    TransferTicketStore,
)
from server.manager.transfers.models import (
    NewTransfer,
    NewTransferAttempt,
    TransferMode,
    TransferOperation,
    TransferStatus,
    TransferTicketRole,
)


@contextmanager
def _running(runtime: DataPlaneRuntime):
    server = DataPlaneHTTPServer(("127.0.0.1", 0), runtime=runtime)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _runtime(
    tmp_path,
    *,
    raw: bytes = b"abcdef",
    mode: TransferMode = TransferMode.LOCAL,
):
    path = tmp_path / "transfers.sqlite"
    requests = TransferStore(path, server_id="public-b2")
    transfer = requests.create(
        NewTransfer(
            idempotency_key="http-transfer",
            operation=TransferOperation.DOWNLOAD,
            principal="alice",
            request_owner_manager_id="public-b2",
            relay_owner_manager_id="public-b2",
            source_server_id="public-b2",
            destination_server_id="public-b2",
            storage_server_id="public-b2",
            job_id="job-1",
            artifact_name="result.bin",
            expected_size=len(raw),
            expected_sha256=hashlib.sha256(raw).hexdigest(),
            expires_at=4_000_000_000.0,
        ),
        dispatch_to="public-b2",
    )
    requests.transition(transfer.transfer_id, TransferStatus.PLANNED)
    attempt = TransferAttemptStore(path, server_id="public-b2").begin(
        NewTransferAttempt(
            attempt_key="http-transfer:1",
            transfer_id=transfer.transfer_id,
            mode=mode,
            relay_owner_manager_id="public-b2",
            connection_owner_manager_id="",
            source_server_id="public-b2",
            destination_server_id="public-b2",
            resume_offset=0,
            expires_at=4_000_000_000.0,
        )
    )
    origin = tmp_path / "origin.bin"
    origin.write_bytes(raw)
    runtime = DataPlaneRuntime(
        server_id="public-b2",
        transfer_database=path,
        staging_root=tmp_path / "incoming",
        origin_resolver=lambda _transfer: origin,
        relay_buffer_bytes=4,
        relay_timeout=1.0,
    )
    return runtime, transfer, attempt


def _ticket(
    runtime: DataPlaneRuntime,
    attempt,
    role: TransferTicketRole,
    *,
    node_id: str = "",
    max_uses: int = 0,
) -> str:
    return runtime.tickets.issue(
        transfer_id=attempt.transfer_id,
        attempt_id=attempt.attempt_id,
        role=role,
        principal="alice",
        node_id=node_id,
        start_offset=0,
        end_offset=attempt.expected_size,
        expires_at=4_000_000_000.0,
        max_uses=max_uses,
    ).bearer


def test_origin_download_requires_authorization_header_and_supports_range(
    tmp_path,
) -> None:
    runtime, _transfer, attempt = _runtime(tmp_path)
    bearer = _ticket(
        runtime, attempt, TransferTicketRole.ORIGIN_READ,
        node_id="public-b2",
    )
    path = f"/v1/transfers/{attempt.attempt_id}/origin"

    with _running(runtime) as base_url:
        request = Request(
            base_url + path,
            headers={
                "Authorization": f"Bearer {bearer}",
                "Range": "bytes=2-4",
                "X-FactorTester-Node-ID": "public-b2",
            },
        )
        with urlopen(request) as response:
            assert response.status == 206
            assert response.read() == b"cde"
            assert response.headers["Content-Range"] == "bytes 2-4/6"

        with pytest.raises(HTTPError) as missing:
            urlopen(base_url + path)
        assert missing.value.code == 403

        with pytest.raises(HTTPError) as query_only:
            urlopen(base_url + path + f"?ticket={bearer}")
        assert query_only.value.code == 403


def test_relay_streams_producer_to_consumer_without_staging_copy(tmp_path) -> None:
    runtime, _transfer, attempt = _runtime(
        tmp_path, mode=TransferMode.SOURCE_PUSH,
    )
    producer_ticket = _ticket(
        runtime,
        attempt,
        TransferTicketRole.PRODUCER,
        node_id="public-b2",
        max_uses=1,
    )
    consumer_ticket = _ticket(
        runtime, attempt, TransferTicketRole.CONSUMER,
    )
    result: dict[str, object] = {}

    with _running(runtime) as base_url:
        consumer_path = f"/v1/transfers/{attempt.attempt_id}/consumer"

        def consume() -> None:
            request = Request(
                base_url + consumer_path,
                headers={"Authorization": f"Bearer {consumer_ticket}"},
            )
            with urlopen(request, timeout=2) as response:
                result["status"] = response.status
                result["body"] = response.read()

        thread = threading.Thread(target=consume, daemon=True)
        thread.start()
        producer = Request(
            base_url + f"/v1/transfers/{attempt.attempt_id}/producer",
            data=b"abcdef",
            headers={
                "Authorization": f"Bearer {producer_ticket}",
                "Content-Type": "application/octet-stream",
                "X-FactorTester-Node-ID": "public-b2",
            },
            method="PUT",
        )
        with urlopen(producer, timeout=2) as response:
            assert response.status == 204
        thread.join(timeout=2)

    assert result == {"status": 200, "body": b"abcdef"}
    assert list((tmp_path / "incoming").rglob("*")) == []


def test_destination_write_verifies_and_atomically_promotes(tmp_path) -> None:
    raw = b"new-source"
    runtime, transfer, attempt = _runtime(tmp_path, raw=raw)
    bearer = _ticket(
        runtime,
        attempt,
        TransferTicketRole.DESTINATION_WRITE,
        node_id="public-b2",
        max_uses=1,
    )

    with _running(runtime) as base_url:
        request = Request(
            base_url + f"/v1/transfers/{attempt.attempt_id}/destination",
            data=raw,
            headers={
                "Authorization": f"Bearer {bearer}",
                "Content-Type": "application/octet-stream",
                "X-FactorTester-Node-ID": "public-b2",
            },
            method="PUT",
        )
        with urlopen(request) as response:
            assert response.status == 201

    target = runtime.destination_path(transfer, attempt)
    assert target.read_bytes() == raw
    assert list(target.parent.glob(".*.transfer.tmp")) == []


def test_wrong_role_node_and_size_are_rejected_before_promotion(tmp_path) -> None:
    runtime, transfer, attempt = _runtime(tmp_path)
    wrong_role = _ticket(runtime, attempt, TransferTicketRole.CONSUMER)
    destination = f"/v1/transfers/{attempt.attempt_id}/destination"

    with _running(runtime) as base_url:
        request = Request(
            base_url + destination,
            data=b"abcdef",
            headers={
                "Authorization": f"Bearer {wrong_role}",
                "X-FactorTester-Node-ID": "public-b2",
            },
            method="PUT",
        )
        with pytest.raises(HTTPError) as denied:
            urlopen(request)
        assert denied.value.code == 403

        valid = _ticket(
            runtime,
            attempt,
            TransferTicketRole.DESTINATION_WRITE,
            node_id="public-b2",
            max_uses=1,
        )
        short = Request(
            base_url + destination,
            data=b"short",
            headers={
                "Authorization": f"Bearer {valid}",
                "X-FactorTester-Node-ID": "public-b2",
            },
            method="PUT",
        )
        with pytest.raises(HTTPError) as mismatch:
            urlopen(short)
        assert mismatch.value.code == 422

    assert not runtime.destination_path(transfer, attempt).exists()
