import inspect

from server.manager.http.job_proxy_routes import JobProxyRoutesMixin
from server.manager.http.streaming import read_available


class SparseStream:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def read1(self, size: int) -> bytes:
        self.calls.append(("read1", size))
        return b"data: sparse\n\n"

    def read(self, size: int) -> bytes:
        self.calls.append(("read", size))
        raise AssertionError("buffer-filling read must not be preferred")


class BasicStream:
    def read(self, size: int) -> bytes:
        return b"fallback" if size == 4096 else b""


def test_sparse_sse_prefers_low_latency_read1() -> None:
    stream = SparseStream()

    assert read_available(stream) == b"data: sparse\n\n"
    assert stream.calls == [("read1", 4096)]


def test_stream_reader_keeps_transport_compatibility_fallback() -> None:
    assert read_available(BasicStream()) == b"fallback"


def test_job_progress_proxy_does_not_write_sqlite_on_each_frame() -> None:
    source = inspect.getsource(JobProxyRoutesMixin._proxy_job_stream)

    assert "job_index" not in source
