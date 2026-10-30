"""Sole host-local producer for bounded, mmap-friendly Arrow cache chunks."""
from __future__ import annotations

from contextlib import nullcontext
import json
import os
from pathlib import Path
import socket
import socketserver
import stat
import threading
from typing import Callable, Iterable

from .protocol import MAX_FRAME_BYTES, DataIOProtocolError, receive_frame, send_frame


MAX_COLUMNS = 256
MAX_ROW_GROUPS = 10_000
MAX_FILTERS = 16


def _validate_request(value: object) -> dict:
    if not isinstance(value, dict) or value.get("operation") != "parquet_handles":
        raise ValueError("unsupported data I/O operation")
    path = value.get("path")
    if not isinstance(path, str) or not path or len(path) > 4096:
        raise ValueError("a bounded source path is required")
    columns = value.get("columns")
    if columns is not None and (
        not isinstance(columns, list) or not columns or len(columns) > MAX_COLUMNS
        or any(not isinstance(item, str) or not item or len(item) > 256 for item in columns)
        or len(set(columns)) != len(columns)
    ):
        raise ValueError("invalid projected columns")
    row_groups = value.get("row_groups")
    if row_groups is not None and (
        not isinstance(row_groups, list) or len(row_groups) > MAX_ROW_GROUPS
        or any(type(item) is not int or item < 0 for item in row_groups)
    ):
        raise ValueError("invalid row-group selection")
    filters = value.get("filters", [])
    if not isinstance(filters, list) or len(filters) > MAX_FILTERS:
        raise ValueError("invalid filter list")
    if filters:
        raise ValueError("filters are not supported for immutable file-handle reads")
    for item in filters:
        if (not isinstance(item, list) or len(item) != 3
                or not isinstance(item[0], str) or len(item[0]) > 256
                or item[1] not in {">=", "<=", "=="}
                or isinstance(item[2], (list, dict))):
            raise ValueError("invalid source filter")
    revision = value.get("revision")
    if revision is not None and (not isinstance(revision, str) or len(revision) > 256):
        raise ValueError("invalid source revision")
    return {"path": path, "columns": columns, "row_groups": row_groups,
            "filters": filters, "revision": revision}


class DataIOService:
    def __init__(self, *, socket_path: str | Path, allowed_roots: Iterable[str | Path],
                 cache_factory: Callable[[], object], max_requests: int = 4,
                 max_chunks_per_request: int = 100_000):
        if not 1 <= max_requests <= 64 or not 1 <= max_chunks_per_request <= 1_000_000:
            raise ValueError("invalid data I/O service limits")
        self.socket_path = Path(socket_path)
        roots = tuple(Path(item).resolve(strict=True) for item in allowed_roots)
        if not roots or any(not item.is_dir() for item in roots):
            raise ValueError("at least one existing allowed data root is required")
        self.allowed_roots = roots
        self.cache_factory = cache_factory
        self.max_chunks_per_request = max_chunks_per_request
        self._slots = threading.BoundedSemaphore(max_requests)

    def resolve_path(self, value: str) -> Path:
        path = Path(value).resolve(strict=True)
        if not path.is_file() or not any(path.is_relative_to(root) for root in self.allowed_roots):
            raise PermissionError("source is outside the data I/O service roots")
        return path

    def stream_handles(self, connection: socket.socket, address, request: dict) -> None:
        args = _validate_request(request)
        path = self.resolve_path(args["path"])
        cache = self.cache_factory()
        admission = getattr(cache, "consumer", None)
        context = admission(interactive=False, timeout=30) if admission else nullcontext()
        count = 0
        with context:
            handles = cache.iter_parquet_handles(
                path, columns=args["columns"], row_groups=args["row_groups"],
                revision=args["revision"],
            )
            try:
                for handle in handles:
                    count += 1
                    if count > self.max_chunks_per_request:
                        raise ValueError("data I/O chunk budget exceeded")
                    size = os.fstat(handle.fileno()).st_size
                    send_frame(connection, {"state": "chunk", "index": count - 1,
                                           "size_bytes": size}, handle.fileno(), address)
                send_frame(connection, {"state": "done", "chunks": count}, address=address)
            finally:
                close = getattr(handles, "close", None)
                if close:
                    close()

    def bind(self):
        self.socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o770)
        if self.socket_path.exists() or self.socket_path.is_symlink():
            info = self.socket_path.lstat()
            if not stat.S_ISSOCK(info.st_mode):
                raise FileExistsError("refusing to replace a non-socket data I/O path")
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            try:
                probe.connect(str(self.socket_path))
                probe.send(b'{"operation":"ping"}\n')
                probe.settimeout(1.0)
                response, _descriptor = receive_frame(probe)
                if response.get("state") != "ready":
                    raise RuntimeError("existing data I/O socket returned an invalid readiness response")
                raise RuntimeError("data I/O service is already listening on this socket")
            except ConnectionRefusedError:
                self.socket_path.unlink()
            except TimeoutError as exc:
                raise RuntimeError("existing data I/O socket did not confirm its state") from exc
            finally:
                probe.close()
        service = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                raw, listener = self.request
                address = self.client_address
                if not isinstance(address, str) or not address:
                    return
                try:
                    if len(raw) > MAX_FRAME_BYTES or not raw.endswith(b"\n"):
                        raise ValueError("data I/O request exceeds frame limit")
                    request = json.loads(raw[:-1])
                except (ValueError, TypeError, json.JSONDecodeError) as exc:
                    try:
                        send_frame(listener, {"state": "error", "message": str(exc)[:512]}, address=address)
                    except OSError:
                        pass
                    return
                if isinstance(request, dict) and request.get("operation") == "ping":
                    send_frame(listener, {"state": "ready"}, address=address)
                    return
                if not service._slots.acquire(blocking=False):
                    send_frame(listener, {"state": "error", "message": "data I/O concurrency limit reached"}, address=address)
                    return
                try:
                    service.stream_handles(listener, address, request)
                except (BrokenPipeError, ConnectionResetError, ConnectionRefusedError):
                    return
                except (ValueError, TypeError, KeyError, OSError, RuntimeError, PermissionError,
                        json.JSONDecodeError, DataIOProtocolError) as exc:
                    try:
                        send_frame(listener, {"state": "error", "message": str(exc)[:512]}, address=address)
                    except OSError:
                        pass
                finally:
                    service._slots.release()

        class UnixServer(socketserver.ThreadingUnixDatagramServer):
            daemon_threads = True
            allow_reuse_address = False

        server = UnixServer(str(self.socket_path), Handler)
        os.chmod(self.socket_path, 0o660)
        return server

    def serve_forever(self) -> None:
        server = self.bind()
        try:
            server.serve_forever(poll_interval=0.5)
        finally:
            server.server_close()
            self.socket_path.unlink(missing_ok=True)


def main() -> None:
    socket_path = Path(os.environ.get("TR_DATA_IO_SOCKET_PATH", "/data-io/data.sock"))
    roots = [item for item in os.environ.get("TR_DATA_IO_ALLOWED_ROOTS", "/data,/node-state").split(",") if item]
    from traderesearch_data.shared_cache import host_input_cache

    DataIOService(socket_path=socket_path, allowed_roots=roots,
                  cache_factory=host_input_cache).serve_forever()


if __name__ == "__main__":
    main()

