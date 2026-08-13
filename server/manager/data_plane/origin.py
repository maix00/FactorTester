"""Serve a fixed local origin file with strict capability-bound ranges."""

from __future__ import annotations

from server.manager.data_plane.authorization import authorize
from server.manager.data_plane.context import DataPlaneRuntime, TransferContext
from server.manager.data_plane.ranges import RangeNotSatisfiable, parse_byte_range
from server.manager.data_plane.responses import empty_response
from server.manager.transfers.models import TransferTicketRole


def serve_origin(
    handler,
    runtime: DataPlaneRuntime,
    context: TransferContext,
) -> None:
    authorize(
        handler,
        runtime,
        context,
        role=TransferTicketRole.ORIGIN_READ,
    )
    path = runtime.origin_path(context)
    size = path.stat().st_size
    if size != context.attempt.expected_size:
        raise RuntimeError("transfer origin size does not match Attempt")
    try:
        selected = parse_byte_range(
            str(handler.headers.get("Range") or ""),
            size=size,
            allowed_start=context.attempt.resume_offset,
            allowed_end=context.attempt.expected_size - 1,
        )
    except RangeNotSatisfiable:
        handler.send_response(416)
        handler.send_header("Content-Range", f"bytes */{size}")
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return
    handler.send_response(206 if selected.partial else 200)
    handler.send_header("Content-Type", "application/octet-stream")
    handler.send_header("Content-Length", str(selected.length))
    handler.send_header("Accept-Ranges", "bytes")
    if selected.partial:
        handler.send_header(
            "Content-Range",
            f"bytes {selected.start}-{selected.end}/{selected.size}",
        )
    handler.send_header("Cache-Control", "private, no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    if handler.command == "HEAD":
        return
    with path.open("rb") as stream:
        stream.seek(selected.start)
        remaining = selected.length
        while remaining:
            chunk = stream.read(min(1024 * 1024, remaining))
            if not chunk:
                raise RuntimeError("transfer origin ended unexpectedly")
            handler.wfile.write(chunk)
            remaining -= len(chunk)

