"""Stream a client upload directly to a WireGuard-reachable destination."""

from __future__ import annotations

from urllib.request import Request

from server.manager.data_plane.authorization import authorize
from server.manager.data_plane.context import DataPlaneRuntime, TransferContext
from server.manager.data_plane.destination import _content_length
from server.manager.data_plane.responses import empty_response
from server.manager.data_plane.streaming import BoundedRequestBody
from server.manager.transfers.models import TransferTicketRole


def serve_direct_push(
    handler,
    runtime: DataPlaneRuntime,
    context: TransferContext,
) -> None:
    authorize(
        handler,
        runtime,
        context,
        role=TransferTicketRole.CLIENT_UPLOAD,
        consume=True,
    )
    remaining = _content_length(handler)
    expected = context.attempt.expected_size - context.attempt.resume_offset
    if remaining != expected:
        raise ValueError(
            f"upload expected {expected} request bytes, received {remaining}"
        )
    if (
        runtime.destination_ticket_provider is None
        or runtime.destination_endpoint_provider is None
    ):
        raise RuntimeError("direct-push providers are unavailable")
    bearer = runtime.destination_ticket_provider(context)
    endpoint = runtime.destination_endpoint_provider(context).rstrip("/")
    request = Request(
        endpoint + f"/v1/transfers/{context.attempt.attempt_id}/destination",
        data=BoundedRequestBody(handler.rfile, length=remaining),
        headers={
            "Authorization": f"Bearer {bearer}",
            "Content-Length": str(remaining),
            "Content-Type": (
                handler.headers.get("Content-Type")
                or "application/octet-stream"
            ),
            "X-FactorTester-Node-ID": runtime.server_id,
        },
        method="PUT",
    )
    with runtime.transport.open(request, timeout=120.0) as response:
        response.read()
        empty_response(handler, response.status)
