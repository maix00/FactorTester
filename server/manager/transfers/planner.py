"""Plan immutable one-hop transfers over the FactorTester WireGuard network."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from server.manager.transfers.models import TransferMode, TransferOperation


class NodeUnavailable(ConnectionError):
    """A transfer peer has no usable FactorTester overlay endpoint."""

    code = "node_unreachable"

    def __init__(self, server_id: str, reason: str) -> None:
        self.server_id = str(server_id or "").strip()
        self.reason = str(reason or "unavailable").strip()
        super().__init__(f"node {self.server_id} is unreachable: {self.reason}")


@dataclass(frozen=True, slots=True)
class NodeEndpoint:
    server_id: str
    peer_data_endpoint: str
    peer_control_endpoint: str
    observed_at: float
    expires_at: float
    online: bool

    def live(self, now: float) -> bool:
        return self.online and self.observed_at <= now < self.expires_at


@dataclass(frozen=True, slots=True)
class TransferPlanningRequest:
    operation: TransferOperation
    request_owner_manager_id: str
    source_server_id: str
    destination_server_id: str
    storage_server_id: str
    client_data_endpoint: str


@dataclass(frozen=True, slots=True)
class TransferPlan:
    mode: TransferMode
    request_owner_manager_id: str
    source_server_id: str
    destination_server_id: str
    client_data_endpoint: str
    source_peer_data_endpoint: str
    source_peer_control_endpoint: str
    destination_peer_data_endpoint: str
    destination_peer_control_endpoint: str


def _required_endpoint(
    endpoints: Mapping[str, NodeEndpoint],
    server_id: str,
    *,
    now: float,
) -> NodeEndpoint:
    value = endpoints.get(server_id)
    if value is None or value.server_id != server_id:
        raise NodeUnavailable(server_id, "endpoint is not registered")
    if not value.live(now):
        raise NodeUnavailable(server_id, "endpoint is offline or stale")
    if not str(value.peer_data_endpoint or "").strip():
        raise NodeUnavailable(server_id, "data endpoint is not advertised")
    if not str(value.peer_control_endpoint or "").strip():
        raise NodeUnavailable(server_id, "control endpoint is not advertised")
    return value


def _operation(request: TransferPlanningRequest) -> TransferOperation:
    operation = TransferOperation(request.operation)
    owner = str(request.request_owner_manager_id or "").strip()
    expected_owner = (
        request.destination_server_id
        if operation is TransferOperation.DOWNLOAD
        else request.source_server_id
    )
    expected_storage = (
        request.source_server_id
        if operation is TransferOperation.DOWNLOAD
        else request.destination_server_id
    )
    if owner != expected_owner:
        raise ValueError("request owner must be the client-facing transfer node")
    if request.storage_server_id != expected_storage:
        raise ValueError("storage server does not match transfer operation")
    if not str(request.client_data_endpoint or "").strip():
        raise ValueError("client data endpoint is required")
    return operation


def plan_transfer(
    request: TransferPlanningRequest,
    *,
    endpoints: Mapping[str, NodeEndpoint],
    now: float,
) -> TransferPlan:
    """Freeze a local or direct route; never infer or fall back to public URLs."""

    operation = _operation(request)
    local = request.source_server_id == request.destination_server_id
    if local:
        return TransferPlan(
            mode=TransferMode.LOCAL,
            request_owner_manager_id=request.request_owner_manager_id,
            source_server_id=request.source_server_id,
            destination_server_id=request.destination_server_id,
            client_data_endpoint=request.client_data_endpoint.rstrip("/"),
            source_peer_data_endpoint="",
            source_peer_control_endpoint="",
            destination_peer_data_endpoint="",
            destination_peer_control_endpoint="",
        )
    source = _required_endpoint(endpoints, request.source_server_id, now=now)
    destination = _required_endpoint(
        endpoints, request.destination_server_id, now=now,
    )
    mode = (
        TransferMode.DIRECT_PULL
        if operation is TransferOperation.DOWNLOAD
        else TransferMode.DIRECT_PUSH
    )
    return TransferPlan(
        mode=mode,
        request_owner_manager_id=request.request_owner_manager_id,
        source_server_id=request.source_server_id,
        destination_server_id=request.destination_server_id,
        client_data_endpoint=request.client_data_endpoint.rstrip("/"),
        source_peer_data_endpoint=source.peer_data_endpoint.rstrip("/"),
        source_peer_control_endpoint=source.peer_control_endpoint.rstrip("/"),
        destination_peer_data_endpoint=(
            destination.peer_data_endpoint.rstrip("/")
        ),
        destination_peer_control_endpoint=(
            destination.peer_control_endpoint.rstrip("/")
        ),
    )
