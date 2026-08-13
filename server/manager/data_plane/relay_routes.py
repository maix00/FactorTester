"""HTTP producer and consumer adapters around the bounded relay registry."""

from __future__ import annotations

from server.manager.data_plane.authorization import authorize
from server.manager.data_plane.context import DataPlaneRuntime, TransferContext
from server.manager.data_plane.destination import _content_length
from server.manager.data_plane.responses import empty_response
from server.manager.transfers.models import TransferTicketRole


def receive_producer(
    handler,
    runtime: DataPlaneRuntime,
    context: TransferContext,
) -> None:
    authorize(
        handler,
        runtime,
        context,
        role=TransferTicketRole.PRODUCER,
        consume=True,
    )
    remaining = _content_length(handler)
    expected = context.attempt.expected_size - context.attempt.resume_offset
    if remaining != expected:
        raise ValueError(
            f"relay expected {expected} request bytes, received {remaining}"
        )
    producer = runtime.relays.attach_producer(
        context.attempt.attempt_id,
        expected_bytes=expected,
    )
    try:
        while remaining:
            chunk = handler.rfile.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("producer request ended before Content-Length")
            producer.write(chunk)
            remaining -= len(chunk)
        producer.finish()
    except BaseException as exc:
        producer.fail(exc)
        raise
    empty_response(handler, 204)


def serve_consumer(
    handler,
    runtime: DataPlaneRuntime,
    context: TransferContext,
) -> None:
    authorize(
        handler,
        runtime,
        context,
        role=TransferTicketRole.CONSUMER,
    )
    expected = context.attempt.expected_size - context.attempt.resume_offset
    handler.send_response(200)
    handler.send_header("Content-Type", "application/octet-stream")
    handler.send_header("Content-Length", str(expected))
    handler.send_header("Cache-Control", "private, no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    if handler.command == "HEAD":
        return
    consumer = runtime.relays.attach_consumer(context.attempt.attempt_id)
    for chunk in consumer.iter_chunks():
        handler.wfile.write(chunk)
