"""Receive one authorized stream into verified private staging storage."""

from __future__ import annotations

from server.manager.data_plane.authorization import authorize
from server.manager.data_plane.context import DataPlaneRuntime, TransferContext
from server.manager.data_plane.integrity import VerifiedStagingWriter
from server.manager.data_plane.responses import empty_response
from server.manager.transfers.models import TransferTicketRole


def receive_destination(
    handler,
    runtime: DataPlaneRuntime,
    context: TransferContext,
) -> None:
    authorize(
        handler,
        runtime,
        context,
        role=TransferTicketRole.DESTINATION_WRITE,
        consume=True,
    )
    remaining = _content_length(handler)
    expected_remaining = (
        context.attempt.expected_size - context.attempt.resume_offset
    )
    if remaining != expected_remaining:
        raise ValueError(
            f"destination expected {expected_remaining} request bytes, "
            f"received {remaining}"
        )
    target = runtime.destination_path(context.transfer, context.attempt)
    writer = VerifiedStagingWriter(
        target,
        expected_size=context.attempt.expected_size,
        expected_sha256=context.attempt.expected_sha256,
        resume_offset=context.attempt.resume_offset,
    )
    try:
        while remaining:
            chunk = handler.rfile.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("destination request ended before Content-Length")
            writer.write(chunk)
            remaining -= len(chunk)
        writer.finish()
    except BaseException:
        writer.cancel()
        raise
    empty_response(handler, 201)


def _content_length(handler) -> int:
    value = str(handler.headers.get("Content-Length") or "").strip()
    if not value:
        raise ValueError("Content-Length is required")
    result = int(value)
    if result < 0:
        raise ValueError("Content-Length must not be negative")
    return result
