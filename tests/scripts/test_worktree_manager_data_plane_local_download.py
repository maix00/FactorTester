from __future__ import annotations

import hashlib
import threading
import time
from contextlib import contextmanager
from urllib.request import Request, urlopen

from server.manager.data_plane.server import DataPlaneHTTPServer, DataPlaneRuntime
from server.manager.storage.transfers import (
    TransferAttemptStore,
    TransferStore,
    TransferTicketStore,
)
from server.manager.transfers.coordinator import DownloadRequest, TransferCoordinator
from server.manager.transfers.planner import NodeReachability


@contextmanager
def _running(runtime):
    server = DataPlaneHTTPServer(("127.0.0.1", 0), runtime=runtime)
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
        data_endpoint="http://placeholder:7997",
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
        observations={
            "public-b2": NodeReachability(
                server_id="public-b2",
                data_endpoint="http://placeholder:7997",
                reachable_from=frozenset({"public-b2"}),
                connection_owner_manager_id="public-b2",
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
