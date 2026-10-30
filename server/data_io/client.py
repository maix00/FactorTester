"""Client for the host-local Arrow file-descriptor service."""
from __future__ import annotations

import os
from pathlib import Path
import socket
import uuid
from typing import Iterator, Sequence

from .protocol import DataIOProtocolError, encode_frame, receive_frame


class DataIOClient:
    def __init__(self, socket_path: str | Path, *, timeout: float = 300.0):
        self.socket_path = str(socket_path)
        self.timeout = timeout

    def iter_parquet_handles(
        self,
        path: str | Path,
        *,
        columns: Sequence[str] | None = None,
        row_groups: Sequence[int] | None = None,
        filters=(),
        revision: str | None = None,
    ) -> Iterator:
        """Yield read-only cache handles; each handle owns an OS descriptor."""
        if os.name == "nt" or not hasattr(socket, "SCM_RIGHTS"):
            raise DataIOProtocolError(
                "local file-handle transport is unavailable on this platform; configure Arrow Flight"
            )
        request = {
            "operation": "parquet_handles",
            "path": str(path),
            "columns": None if columns is None else list(columns),
            "row_groups": None if row_groups is None else list(row_groups),
            "filters": [list(item) for item in filters],
            "revision": revision,
        }
        raw = encode_frame(request)
        local_path = Path("/tmp") / f"tr-dio-{uuid.uuid4().hex}.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.settimeout(self.timeout)
            sock.bind(str(local_path))
            try:
                sock.connect(self.socket_path)
                sock.send(raw)
                expected_index = 0
                while True:
                    response, descriptor = receive_frame(sock)
                    state = response.get("state")
                    if state == "done":
                        if descriptor is not None:
                            os.close(descriptor)
                            raise DataIOProtocolError("done response unexpectedly carried a descriptor")
                        if response.get("chunks") != expected_index:
                            raise DataIOProtocolError("data I/O chunk count changed in transit")
                        return
                    if state == "error":
                        if descriptor is not None:
                            os.close(descriptor)
                        raise DataIOProtocolError(str(response.get("message") or "data I/O request failed"))
                    if state != "chunk" or descriptor is None:
                        if descriptor is not None:
                            os.close(descriptor)
                        raise DataIOProtocolError("invalid Arrow handle response")
                    if response.get("index") != expected_index:
                        os.close(descriptor)
                        raise DataIOProtocolError("data I/O chunk sequence is invalid")
                    if type(response.get("size_bytes")) is not int or response["size_bytes"] < 0:
                        os.close(descriptor)
                        raise DataIOProtocolError("invalid Arrow handle size")
                    try:
                        actual_size = os.fstat(descriptor).st_size
                        if actual_size != response["size_bytes"]:
                            raise DataIOProtocolError("Arrow handle size changed in transit")
                        yield os.fdopen(descriptor, "rb", closefd=True)
                        expected_index += 1
                    except BaseException:
                        try:
                            os.close(descriptor)
                        except OSError:
                            pass
                        raise
            finally:
                local_path.unlink(missing_ok=True)

    def ping(self) -> bool:
        local_path = Path("/tmp") / f"tr-dio-{uuid.uuid4().hex}.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.settimeout(min(self.timeout, 2.0))
            sock.bind(str(local_path))
            try:
                sock.connect(self.socket_path)
                sock.send(encode_frame({"operation": "ping"}))
                value, descriptor = receive_frame(sock)
                if descriptor is not None:
                    os.close(descriptor)
                    return False
                return value.get("state") == "ready"
            finally:
                local_path.unlink(missing_ok=True)

