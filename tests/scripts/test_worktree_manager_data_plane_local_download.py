from __future__ import annotations

import gzip
import hashlib
import threading
import time
from contextlib import contextmanager
from urllib.request import Request, urlopen

from server.manager.data_plane.server import (
    ClientDataPlaneHTTPServer,
    DataPlaneRuntime,
)
from server.manager.storage.transfers import (
    TransferAttemptStore,
    TransferStore,
    TransferTicketStore,
)
from server.manager.transfers.coordinator import DownloadRequest, TransferCoordinator
from server.manager.transfers.planner import NodeEndpoint


@contextmanager
def _running(runtime):
    server = ClientDataPlaneHTTPServer(("127.0.0.1", 0), runtime=runtime)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_client_consumer_route_streams_local_origin(tmp_path) -> None:
    raw = b"local-artifact"
    database = tmp_path / "transfers.sqlite"
    coordinator = TransferCoordinator(
        manager_id="public-b2",
        client_data_endpoint="http://placeholder:7997",
        requests=TransferStore(database, server_id="public-b2"),
        attempts=TransferAttemptStore(database, server_id="public-b2"),
        tickets=TransferTicketStore(database, server_id="public-b2"),
    )
    now = time.time()
    access = coordinator.prepare_download(
        DownloadRequest(
            idempotency_key="local-http",
            principal="alice",
            storage_server_id="public-b2",
            job_id="job-1",
            artifact_name="result.bin",
            expected_size=len(raw),
            expected_sha256=hashlib.sha256(raw).hexdigest(),
            expires_at=4_000_000_000.0,
        ),
        endpoints={
            "public-b2": NodeEndpoint(
                server_id="public-b2",
                peer_data_endpoint="http://10.77.0.2:17997",
                peer_control_endpoint="http://10.77.0.2:17998",
                observed_at=now,
                expires_at=4_000_000_000.0,
                online=True,
            ),
        },
        now=now,
    )
    origin = tmp_path / "result.bin"
    origin.write_bytes(raw)
    runtime = DataPlaneRuntime(
        server_id="public-b2",
        transfer_database=database,
        staging_root=tmp_path / "incoming",
        origin_resolver=lambda _transfer: origin,
    )

    with _running(runtime) as endpoint:
        request = Request(
            endpoint + access.path,
            headers={"Authorization": f"Bearer {access.bearer}"},
        )
        with urlopen(request) as response:
            assert response.status == 200
            assert response.read() == raw

    summary = runtime.telemetry.summary(now=time.time(), since=now - 10)
    assert summary["totals"]["transferred_bytes"] == len(raw)
    assert summary["dimensions"][0]["surface"] == "client"
    assert summary["dimensions"][0]["action"] == "download"


def test_client_consumer_compresses_large_json_without_affecting_ranges(
    tmp_path,
) -> None:
    raw = (
        b'{"rows":['
        + b'{"value":1},' * 30_000
        + b'{"value":1}]}'
    )
    database = tmp_path / "compressed-transfers.sqlite"
    coordinator = TransferCoordinator(
        manager_id="public-b2",
        client_data_endpoint="http://placeholder:7997",
        requests=TransferStore(database, server_id="public-b2"),
        attempts=TransferAttemptStore(database, server_id="public-b2"),
        tickets=TransferTicketStore(database, server_id="public-b2"),
    )
    now = time.time()
    access = coordinator.prepare_download(
        DownloadRequest(
            idempotency_key="large-json-http",
            principal="alice",
            storage_server_id="public-b2",
            job_id="job-1",
            artifact_name="result.json",
            expected_size=len(raw),
            expected_sha256=hashlib.sha256(raw).hexdigest(),
            expires_at=4_000_000_000.0,
            content_type="application/json",
        ),
        endpoints={
            "public-b2": NodeEndpoint(
                server_id="public-b2",
                peer_data_endpoint="http://10.77.0.2:17997",
                peer_control_endpoint="http://10.77.0.2:17998",
                observed_at=now,
                expires_at=4_000_000_000.0,
                online=True,
            ),
        },
        now=now,
    )
    origin = tmp_path / "result.json"
    origin.write_bytes(raw)
    runtime = DataPlaneRuntime(
        server_id="public-b2",
        transfer_database=database,
        staging_root=tmp_path / "incoming",
        origin_resolver=lambda _transfer: origin,
    )

    with _running(runtime) as endpoint:
        headers = {
            "Authorization": f"Bearer {access.bearer}",
            "Accept-Encoding": "gzip",
        }
        with urlopen(Request(endpoint + access.path, headers=headers)) as response:
            assert response.status == 200
            assert response.headers["Content-Encoding"] == "gzip"
            assert response.headers.get("Content-Length") is None
            assert gzip.decompress(response.read()) == raw
        summary = runtime.telemetry.summary(now=time.time(), since=now - 10)
        assert summary["totals"]["transferred_bytes"] == len(raw)

        with urlopen(Request(
            endpoint + access.path,
            headers={**headers, "Range": "bytes=0-1023"},
        )) as response:
            assert response.status == 206
            assert response.headers.get("Content-Encoding") is None
            assert response.headers["Content-Length"] == "1024"
            assert response.read() == raw[:1024]
