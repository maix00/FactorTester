"""Authorization-header capability checks for transfer data routes."""

from __future__ import annotations

from server.manager.data_plane.context import DataPlaneRuntime, TransferContext
from server.manager.transfers.models import TransferTicketGrant, TransferTicketRole


def bearer_token(handler) -> str:
    scheme, separator, value = str(
        handler.headers.get("Authorization") or ""
    ).partition(" ")
    if not separator or scheme.lower() != "bearer" or not value.strip():
        raise PermissionError("transfer bearer capability is required")
    return value.strip()


def authorize(
    handler,
    runtime: DataPlaneRuntime,
    context: TransferContext,
    *,
    role: TransferTicketRole,
    consume: bool = False,
) -> TransferTicketGrant:
    node_id = str(handler.headers.get("X-FactorTester-Node-ID") or "").strip()
    grant = runtime.tickets.verify(
        bearer_token(handler),
        required_role=role,
        attempt_id=context.attempt.attempt_id,
        node_id=node_id,
        start_offset=context.attempt.resume_offset,
        end_offset=context.attempt.expected_size,
        consume=consume,
    )
    runtime.authorize_transfer_telemetry(handler)
    return grant
