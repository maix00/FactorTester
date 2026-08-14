from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from server.manager.data_plane.server import (
    ClientDataPlaneHTTPServer,
    DataPlaneRuntime,
    PeerDataPlaneHTTPServer,
)
from server.manager.storage.transfers import TransferAttemptStore, TransferStore
from server.manager.transfers.models import (
    AttemptRouteSnapshot,
    NewTransfer,
    NewTransferAttempt,
    TransferMode,
    TransferOperation,
    TransferStatus,
)


@contextmanager
def _running(server_type, runtime):
    server = server_type(("127.0.0.1", 0), runtime=runtime)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _runtime(tmp_path):
    path = tmp_path / "transfers.sqlite"
    requests = TransferStore(path, server_id="node-a")
    transfer = requests.create(NewTransfer(
        idempotency_key="surface-isolation",
        operation=TransferOperation.DOWNLOAD,
        principal="alice",
        request_owner_manager_id="node-a",
        source_server_id="node-a",
        destination_server_id="node-a",
        storage_server_id="node-a",
        job_id="job-1",
        artifact_name="result.bin",
        expected_size=6,
        expected_sha256=hashlib.sha256(b"abcdef").hexdigest(),
        expires_at=4_000_000_000.0,
    ))
    requests.transition(transfer.transfer_id, TransferStatus.PLANNED)
    attempt = TransferAttemptStore(path, server_id="node-a").begin(
        NewTransferAttempt(
            attempt_key="surface-isolation:1",
            transfer_id=transfer.transfer_id,
            mode=TransferMode.LOCAL,
            request_owner_manager_id="node-a",
            source_server_id="node-a",
            destination_server_id="node-a",
            resume_offset=0,
            expires_at=transfer.expires_at,
            routes=AttemptRouteSnapshot(
                client_data_endpoint="https://factor.example:7997",
                source_peer_data_endpoint="http://10.77.0.1:17997",
                source_peer_control_endpoint="http://10.77.0.1:17998",
                destination_peer_data_endpoint="http://10.77.0.1:17997",
                destination_peer_control_endpoint="http://10.77.0.1:17998",
            ),
        )
    )
    origin = tmp_path / "origin.bin"
    origin.write_bytes(b"abcdef")
    return DataPlaneRuntime(
        server_id="node-a",
        transfer_database=path,
        staging_root=tmp_path / "incoming",
        origin_resolver=lambda _transfer: origin,
    ), attempt


@pytest.mark.parametrize(
    ("server_type", "action"),
    [
        (ClientDataPlaneHTTPServer, "origin"),
        (ClientDataPlaneHTTPServer, "destination"),
        (PeerDataPlaneHTTPServer, "download"),
        (PeerDataPlaneHTTPServer, "upload"),
    ],
)
def test_client_and_peer_routes_are_not_visible_on_the_other_listener(
    tmp_path,
    server_type,
    action: str,
) -> None:
    runtime, attempt = _runtime(tmp_path)
    with _running(server_type, runtime) as endpoint:
        request = Request(
            endpoint + f"/v1/transfers/{attempt.attempt_id}/{action}",
            data=b"abcdef" if action in {"upload", "destination"} else None,
            method="PUT" if action in {"upload", "destination"} else "GET",
        )
        with pytest.raises(HTTPError) as denied:
            urlopen(request)

    assert denied.value.code == 404
    payload = json.loads(denied.value.read())
    assert payload["error"]["code"] == "transfer_error"


def test_client_health_does_not_disclose_peer_endpoint(tmp_path) -> None:
    runtime, _attempt = _runtime(tmp_path)
    with _running(ClientDataPlaneHTTPServer, runtime) as endpoint:
        with urlopen(endpoint + "/healthz") as response:
            payload = json.loads(response.read())

    assert payload["surface"] == "client"
    assert "endpoint" not in payload
    with sqlite3.connect(runtime.requests.path) as connection:
        assert connection.execute(
            "SELECT source_peer_data_endpoint FROM transfer_attempts"
        ).fetchone()[0].endswith(":17997")
