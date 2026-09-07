from __future__ import annotations

import hashlib
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from server.manager.data_plane.context import DataPlaneRuntime
from server.manager.data_plane.server import (
    ClientDataPlaneHTTPServer,
    PeerDataPlaneHTTPServer,
)
from server.manager.storage.transfers import (
    TransferAttemptStore,
    TransferReplicaStore,
    TransferStore,
    TransferTicketStore,
)
from server.manager.transfers.coordinator import DownloadRequest, TransferCoordinator
from server.manager.transfers.models import TransferTicketRole
from server.manager.transfers.planner import NodeEndpoint


class _NoopPeerGateway:
    @staticmethod
    def import_context(_transfer, _attempt) -> None:
        pass


@contextmanager
def _running(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _node(
    node_id: str, data_endpoint: str, octet: int, *, now: float,
) -> NodeEndpoint:
    return NodeEndpoint(
        server_id=node_id,
        peer_data_endpoint=data_endpoint,
        peer_control_endpoint=f"http://10.77.0.{octet}:17998",
        observed_at=now,
        expires_at=now + 600,
        online=True,
    )


@contextmanager
def _direct_download(
    tmp_path, raw: bytes, *, content_type: str = "application/octet-stream",
):
    source_db = tmp_path / "source.sqlite"
    requester_db = tmp_path / "requester.sqlite"
    source_file = tmp_path / "source.bin"
    source_file.write_bytes(raw)
    now = time.time()
    source_runtime = DataPlaneRuntime(
        server_id="node-a",
        transfer_database=source_db,
        staging_root=tmp_path / "source-staging",
        origin_resolver=lambda _transfer: source_file,
    )
    source_server = PeerDataPlaneHTTPServer(
        ("127.0.0.1", 0), runtime=source_runtime,
    )
    with _running(source_server) as source_endpoint:
        coordinator = TransferCoordinator(
            manager_id="node-b",
            client_data_endpoint="http://client-placeholder:7997",
            requests=TransferStore(requester_db, server_id="node-b"),
            attempts=TransferAttemptStore(requester_db, server_id="node-b"),
            tickets=TransferTicketStore(requester_db, server_id="node-b"),
            peer_gateway=_NoopPeerGateway(),
        )
        access = coordinator.prepare_download(
            DownloadRequest(
                idempotency_key="wireguard-direct-download",
                principal="alice",
                storage_server_id="node-a",
                job_id="job-1",
                artifact_name="result.bin",
                expected_size=len(raw),
                expected_sha256=hashlib.sha256(raw).hexdigest(),
                expires_at=now + 600,
                content_type=content_type,
            ),
            endpoints={
                "node-a": _node("node-a", source_endpoint, 1, now=now),
                "node-b": _node(
                    "node-b", "http://10.77.0.2:17997", 2, now=now,
                ),
            },
            now=now,
        )
        transfer = coordinator.requests.require(access.transfer_id)
        attempt = coordinator.attempts.require(access.attempt_id)
        TransferReplicaStore(
            source_db, server_id="node-a",
        ).import_context(transfer, attempt, now=now)
        origin_bearer = source_runtime.tickets.issue(
            transfer_id=transfer.transfer_id,
            attempt_id=attempt.attempt_id,
            role=TransferTicketRole.ORIGIN_READ,
            principal=transfer.principal,
            node_id="node-b",
            start_offset=0,
            end_offset=len(raw),
            expires_at=transfer.expires_at,
        ).bearer
        requester_runtime = DataPlaneRuntime(
            server_id="node-b",
            transfer_database=requester_db,
            staging_root=tmp_path / "requester-staging",
            origin_resolver=lambda _transfer: Path("/not-local"),
            origin_ticket_provider=lambda _context: origin_bearer,
        )
        requester_server = ClientDataPlaneHTTPServer(
            ("127.0.0.1", 0), runtime=requester_runtime,
        )
        with _running(requester_server) as requester_endpoint:
            yield requester_endpoint, access, requester_runtime


def test_direct_pull_streams_range_and_head_without_relay_copy(tmp_path, monkeypatch) -> None:
    raw = b"wireguard-direct-artifact"
    with _direct_download(tmp_path, raw) as (endpoint, access, runtime):
        handles = []
        begin = runtime.begin_transfer_telemetry
        def track_begin(*args, **kwargs):
            handle = begin(*args, **kwargs)
            handles.append(handle)
            return handle
        monkeypatch.setattr(runtime, "begin_transfer_telemetry", track_begin)
        headers = {"Authorization": f"Bearer {access.bearer}"}
        with urlopen(Request(
            endpoint + access.path,
            headers={**headers, "Range": "bytes=10-15"},
        )) as response:
            assert response.status == 206
            assert response.headers["Content-Range"] == (
                f"bytes 10-15/{len(raw)}"
            )
            assert response.read() == raw[10:16]
        with urlopen(Request(
            endpoint + access.path, headers=headers, method="HEAD",
        )) as response:
            assert response.status == 200
            assert response.headers["Content-Length"] == str(len(raw))
            assert response.read() == b""

        assert len(handles) == 1, "HEAD must not overwrite GET telemetry"
        summary = None
        for _ in range(20):
            summary = runtime.telemetry.summary(
                now=time.time(), since=time.time() - 10,
            )
            if summary["totals"]["transferred_bytes"] == 6:
                break
            time.sleep(0.05)
        assert summary is not None
        assert summary["totals"]["transferred_bytes"] == 6
        assert summary["dimensions"][0]["mode"] == "direct_pull"
        assert summary["dimensions"][0]["surface"] == "client"

    assert not any(runtime.staging_root.rglob("*"))


def test_direct_pull_forwards_unsatisfied_range(tmp_path) -> None:
    raw = b"short"
    with _direct_download(tmp_path, raw) as (endpoint, access, _runtime):
        request = Request(
            endpoint + access.path,
            headers={
                "Authorization": f"Bearer {access.bearer}",
                "Range": "bytes=99-100",
            },
        )
        with pytest.raises(HTTPError) as denied:
            urlopen(request)

    assert denied.value.code == 416
    assert denied.value.headers["Content-Range"] == f"bytes */{len(raw)}"


def test_direct_pull_preserves_svg_media_type(tmp_path) -> None:
    raw = b'<svg xmlns="http://www.w3.org/2000/svg"><title>curve</title></svg>'
    with _direct_download(
        tmp_path, raw, content_type="image/svg+xml",
    ) as (endpoint, access, _runtime):
        with urlopen(Request(
            endpoint + access.path,
            headers={"Authorization": f"Bearer {access.bearer}"},
        )) as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == "image/svg+xml"
            assert response.read() == raw
