"""Pull a source node's WireGuard 17997 stream without local persistence."""

from __future__ import annotations

from urllib.error import HTTPError
from urllib.request import Request

from server.manager.data_plane.authorization import authorize
from server.manager.data_plane.context import DataPlaneRuntime, TransferContext
from server.manager.transfers.models import TransferTicketRole


_FORWARDED_RESPONSE_HEADERS = (
    "Content-Length",
    "Content-Range",
    "Accept-Ranges",
    "ETag",
)


def serve_direct_pull(
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
    try:
        runtime.lifecycle.start(context.attempt.attempt_id)
        if runtime.origin_ticket_provider is None:
            raise RuntimeError("direct-pull ticket provider is unavailable")
        bearer = runtime.origin_ticket_provider(context)
        endpoint = context.attempt.routes.source_peer_data_endpoint.rstrip("/")
        if runtime.source_endpoint_provider is not None:
            supplied = runtime.source_endpoint_provider(context).rstrip("/")
            if supplied != endpoint:
                raise RuntimeError(
                    "source provider changed the immutable peer route"
                )
        request_headers = {
            "Authorization": f"Bearer {bearer}",
            "X-FactorTester-Node-ID": runtime.server_id,
        }
        byte_range = str(handler.headers.get("Range") or "").strip()
        if byte_range:
            request_headers["Range"] = byte_range
        request = Request(
            endpoint + f"/v1/transfers/{context.attempt.attempt_id}/origin",
            headers=request_headers,
            method="GET" if handler.command != "HEAD" else "HEAD",
        )
        try:
            upstream = runtime.transport.open(request, timeout=30.0)
        except HTTPError as exc:
            upstream = exc
        with upstream:
            handler.send_response(upstream.status)
            handler.send_header(
                "Content-Type",
                upstream.headers.get("Content-Type")
                or "application/octet-stream",
            )
            for name in _FORWARDED_RESPONSE_HEADERS:
                value = upstream.headers.get(name)
                if value:
                    handler.send_header(name, value)
            handler.send_header("Cache-Control", "private, no-store")
            handler.send_header("X-Content-Type-Options", "nosniff")
            handler.end_headers()
            content_length = upstream.headers.get("Content-Length")
            if content_length:
                try:
                    runtime.set_transfer_expected_bytes(
                        handler, int(content_length),
                    )
                except ValueError:
                    pass
            if handler.command != "HEAD":
                while chunk := upstream.read(1024 * 1024):
                    handler.wfile.write(chunk)
                    runtime.record_transfer_bytes(handler, len(chunk))
    except BaseException as exc:
        runtime.lifecycle.fail(context.attempt.attempt_id, exc)
        raise
    runtime.lifecycle.complete(context.attempt.attempt_id)
