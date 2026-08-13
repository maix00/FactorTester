"""Signed one-hop peer-control operations over frozen WireGuard endpoints."""

from __future__ import annotations

from server.manager.transfers.node_client import NodeControlClient
from server.manager.transfers.node_keys import NodeKey
from server.manager.transfers.wire import transfer_context_payload


class TransferPeerGateway:
    def __init__(self, *, key: NodeKey, transport=None) -> None:
        self.key = key
        self.transport = transport

    def import_context(self, transfer, attempt) -> None:
        endpoint = _storage_control_endpoint(transfer, attempt)
        self._client(endpoint).signed_json(
            "/api/federation/transfers/context",
            transfer_context_payload(transfer, attempt),
        )

    def origin_ticket(self, context) -> str:
        value = self._client(
            context.attempt.routes.source_peer_control_endpoint,
        ).signed_json(
            "/api/federation/transfers/origin-ticket",
            {"attempt_id": context.attempt.attempt_id},
        )
        return _bearer(value)

    def destination_ticket(self, context) -> str:
        value = self._client(
            context.attempt.routes.destination_peer_control_endpoint,
        ).signed_json(
            "/api/federation/transfers/destination-ticket",
            {"attempt_id": context.attempt.attempt_id},
        )
        return _bearer(value)

    def _client(self, endpoint: str) -> NodeControlClient:
        return NodeControlClient(
            endpoint,
            key=self.key,
            transport=self.transport,
        )


def _storage_control_endpoint(transfer, attempt) -> str:
    endpoint = (
        attempt.routes.source_peer_control_endpoint
        if transfer.operation.value == "download"
        else attempt.routes.destination_peer_control_endpoint
    )
    if not endpoint:
        raise ConnectionError("storage peer control endpoint is unavailable")
    return endpoint


def _bearer(value: dict[str, object]) -> str:
    result = str(value.get("bearer") or "").strip()
    if not result:
        raise ConnectionError("peer ticket response is incomplete")
    return result
