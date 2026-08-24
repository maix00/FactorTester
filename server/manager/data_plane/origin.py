"""Serve a fixed local origin file with strict capability-bound ranges."""

from __future__ import annotations

import gzip

from server.manager.data_plane.authorization import authorize
from server.manager.data_plane.context import DataPlaneRuntime, TransferContext
from server.manager.data_plane.ranges import RangeNotSatisfiable, parse_byte_range
from server.manager.transfers.models import TransferTicketRole

_GZIP_MINIMUM_BYTES = 256 * 1024


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
    # Origin reads are also consumed by the peer transfer protocol.  Keep
    # those bytes byte-for-byte identical so the immutable hash/size contract
    # remains independent of a browser's Accept-Encoding header.
    _serve_with_lifecycle(handler, runtime, context, allow_compression=False)


def serve_local_download(
    handler,
    runtime: DataPlaneRuntime,
    context: TransferContext,
) -> None:
    authorize(
        handler,
        runtime,
        context,
        role=TransferTicketRole.CLIENT_DOWNLOAD,
    )
    _serve_with_lifecycle(handler, runtime, context, allow_compression=True)


def _serve_with_lifecycle(
    handler,
    runtime,
    context,
    *,
    allow_compression: bool,
) -> None:
    runtime.lifecycle.start(context.attempt.attempt_id)
    try:
        serve_local_file(
            handler, runtime, context, allow_compression=allow_compression,
        )
    except BaseException as exc:
        runtime.lifecycle.fail(context.attempt.attempt_id, exc)
        raise
    runtime.lifecycle.complete(context.attempt.attempt_id)


def serve_local_file(
    handler,
    runtime: DataPlaneRuntime,
    context: TransferContext,
    *,
    allow_compression: bool = False,
) -> None:
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
    compressed = (
        allow_compression
        and handler.command == "GET"
        and not selected.partial
        and selected.length >= _GZIP_MINIMUM_BYTES
        and _is_json_or_text(context.transfer.content_type)
        and _accepts_gzip(handler.headers.get("Accept-Encoding"))
    )
    handler.send_response(206 if selected.partial else 200)
    handler.send_header(
        "Content-Type",
        context.transfer.content_type or "application/octet-stream",
    )
    if not compressed:
        handler.send_header("Content-Length", str(selected.length))
    else:
        # The compressed length is not known without buffering the complete
        # artifact.  HTTP/1.0 close-delimited streaming keeps memory bounded;
        # browsers transparently decompress the response before text/blob
        # consumers see it.
        handler.send_header("Content-Encoding", "gzip")
        handler.send_header("Vary", "Accept-Encoding")
        handler.send_header("Connection", "close")
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
    runtime.set_transfer_expected_bytes(handler, selected.length)
    with path.open("rb") as stream:
        stream.seek(selected.start)
        remaining = selected.length
        if compressed:
            with gzip.GzipFile(fileobj=handler.wfile, mode="wb") as output:
                _write_chunks(handler, runtime, stream, remaining, output)
        else:
            _write_chunks(handler, runtime, stream, remaining, handler.wfile)


def _write_chunks(handler, runtime, stream, remaining: int, output) -> None:
    while remaining:
        chunk = stream.read(min(1024 * 1024, remaining))
        if not chunk:
            raise RuntimeError("transfer origin ended unexpectedly")
        output.write(chunk)
        runtime.record_transfer_bytes(handler, len(chunk))
        remaining -= len(chunk)


def _is_json_or_text(content_type: str) -> bool:
    media_type = str(content_type or "").split(";", 1)[0].strip().lower()
    return media_type == "application/json" or media_type.startswith("text/")


def _accepts_gzip(value: object) -> bool:
    for item in str(value or "").split(","):
        parts = [part.strip() for part in item.split(";")]
        if not parts or parts[0].lower() != "gzip":
            continue
        quality = next(
            (
                part.split("=", 1)[1].strip()
                for part in parts[1:]
                if part.lower().startswith("q=") and "=" in part
            ),
            "1",
        )
        try:
            return float(quality) > 0
        except ValueError:
            return False
    return False
