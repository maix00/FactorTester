"""Same-host Arrow IPC handles are served by one bounded cache producer."""
from __future__ import annotations

from pathlib import Path
import threading
import time
import uuid

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from server.data_io.client import DataIOClient
from server.data_io.protocol import DataIOProtocolError
from server.data_io.service import DataIOService
from traderesearch_data.shared_cache import CacheScope, SharedColumnarCache


@pytest.fixture
def data_io(tmp_path):
    pytest.importorskip("socket")
    if not hasattr(__import__("socket"), "SCM_RIGHTS"):
        pytest.skip("Unix file-descriptor passing is unavailable")
    source_root = tmp_path / "data"
    source_root.mkdir()
    cache = SharedColumnarCache(
        tmp_path / "cache", CacheScope("server", "test-manager", "platform", "test-device"),
        max_bytes=8 * 1024 * 1024, max_entry_bytes=1024 * 1024, max_entries=64,
    )
    socket_path = Path("/tmp") / f"trdio-{uuid.uuid4().hex}.sock"
    service = DataIOService(socket_path=socket_path, allowed_roots=[source_root],
                            cache_factory=lambda: cache, max_requests=2)
    server = service.bind()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    deadline = time.monotonic() + 2
    while not socket_path.exists() and time.monotonic() < deadline:
        time.sleep(0.005)
    try:
        yield source_root, cache, DataIOClient(socket_path, timeout=5)
    finally:
        server.shutdown()
        server.server_close()
        socket_path.unlink(missing_ok=True)
        thread.join(timeout=2)


def _write_source(path: Path, rows=9000):
    table = pa.table({"ts_init": range(rows), "close": [float(i) for i in range(rows)]})
    pq.write_table(table, path, row_group_size=4096)


def _read_handle(handle):
    with handle:
        arrow_file = pa.PythonFile(handle, mode="r")
        try:
            reader = pa.ipc.open_file(arrow_file)
            return [reader.get_batch(i).num_rows for i in range(reader.num_record_batches)]
        finally:
            arrow_file.close()


def test_mmap_ready_handles_are_sent_without_arrow_payload_copy(data_io, tmp_path):
    source_root, cache, client = data_io
    assert client.ping()
    path = source_root / "bars.parquet"
    _write_source(path)

    first = [_read_handle(handle) for handle in client.iter_parquet_handles(path)]
    published = {item.name: item.stat().st_ino for item in cache.root.glob("*.arrow")}
    second = [_read_handle(handle) for handle in client.iter_parquet_handles(path)]

    assert first == second == [[4096], [4096], [808]]
    assert len(published) == 3
    assert {item.name: item.stat().st_ino for item in cache.root.glob("*.arrow")} == published


def test_source_root_is_enforced_after_symlink_resolution(data_io, tmp_path):
    source_root, _cache, client = data_io
    outside = tmp_path / "private.parquet"
    pq.write_table(pa.table({"value": [1]}), outside)
    with pytest.raises(DataIOProtocolError, match="outside the data I/O service roots"):
        list(client.iter_parquet_handles(outside))
    link = source_root / "escape.parquet"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(DataIOProtocolError, match="outside the data I/O service roots"):
        list(client.iter_parquet_handles(link))


def test_invalid_request_is_rejected_and_socket_never_falls_back(data_io, tmp_path, monkeypatch):
    source_root, _cache, client = data_io
    with pytest.raises(DataIOProtocolError, match="projected columns"):
        list(client.iter_parquet_handles(source_root / "missing.parquet", columns=[]))

    monkeypatch.setenv("TR_DATA_IO_SOCKET_PATH", f"/tmp/trdio-missing-{uuid.uuid4().hex}.sock")
    from server.services.nautilus_bridge.shared_inputs import _iter_handles
    with pytest.raises(FileNotFoundError):
        list(_iter_handles(source_root / "missing.parquet"))


def test_windows_does_not_fall_back_to_process_local_cache(monkeypatch, tmp_path):
    from server.data_io import client as client_module

    client = DataIOClient(tmp_path / "unused.sock")
    with monkeypatch.context() as patch:
        patch.setattr(client_module.os, "name", "nt")
        with pytest.raises(DataIOProtocolError, match="configure Arrow Flight"):
            list(client.iter_parquet_handles(tmp_path / "input.parquet"))


def test_execution_node_compose_keeps_arrow_cache_and_socket_on_one_host():
    import yaml

    path = Path(__file__).resolve().parents[2] / "deploy/docker/execution-node/compose.yaml"
    compose = yaml.safe_load(path.read_text())
    worker = compose["services"]["worker"]
    data_io = compose["services"]["data-io"]
    assert worker["environment"]["TR_DATA_IO_SOCKET_PATH"] == "/data-io/data.sock"
    assert data_io["environment"]["TR_SHARED_DATA_CACHE_ROOT"] == "/shared-cache"
    assert "depends_on" in worker and "data-io" in worker["depends_on"]
    assert not data_io.get("ports")
    assert any("TR_DATA_IO_SOCKET_ROOT" in volume for volume in worker["volumes"])
    assert any("TR_DATA_IO_SOCKET_ROOT" in volume for volume in data_io["volumes"])
    assert any("TR_SHARED_CACHE_ROOT" in volume for volume in worker["volumes"])
    assert any("TR_SHARED_CACHE_ROOT" in volume for volume in data_io["volumes"])

