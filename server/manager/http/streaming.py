"""Small streaming helpers shared by local and federated HTTP proxies."""

from __future__ import annotations

from typing import BinaryIO


def read_available(stream: BinaryIO, size: int = 4096) -> bytes:
    """Return currently available bytes without waiting to fill ``size``.

    ``http.client.HTTPResponse.read`` may coalesce a sparse SSE stream until
    the requested byte count is filled. ``read1`` preserves frame latency.
    Test doubles and alternate transports that only implement ``read`` keep a
    narrow compatibility fallback.
    """
    read1 = getattr(stream, "read1", None)
    if callable(read1):
        return read1(size)
    return stream.read(size)
