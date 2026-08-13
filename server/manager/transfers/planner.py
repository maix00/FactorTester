"""Pure reachability planner for one immutable Transfer Attempt topology."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from server.manager.transfers.models import TransferMode, TransferOperation


@dataclass(frozen=True, slots=True)
class NodeReachability:
    server_id: str
    data_endpoint: str
    reachable_from: frozenset[str]
    connection_owner_manager_id: str
    observed_at: float
    expires_at: float
    online: bool
    control_endpoint: str = ""
    connection_owner_control_endpoint: str = ""

    def live(self, now: float) -> bool:
        return self.online and self.observed_at <= now < self.expires_at


@dataclass(frozen=True, slots=True)
class TransferPlanningRequest:
    operation: TransferOperation
    relay_owner_manager_id: str
    source_server_id: str
    destination_server_id: str
    storage_server_id: str
    relay_data_endpoint: str = ""
    request_owner_control_endpoint: str = ""


@dataclass(frozen=True, slots=True)
class TransferPlan:
    mode: TransferMode
    relay_owner_manager_id: str
    connection_owner_manager_id: str
    source_server_id: str
    destination_server_id: str
    commanded_server_id: str
    source_data_endpoint: str
    source_control_endpoint: str
    destination_data_endpoint: str
    destination_control_endpoint: str
    relay_data_endpoint: str
    request_owner_control_endpoint: str
    connection_owner_control_endpoint: str
    hop_budget: int = 1


def _live_node(
    observations: Mapping[str, NodeReachability],
    server_id: str,
    *,
    now: float,
) -> NodeReachability:
    value = observations.get(server_id)
    if value is None or value.server_id != server_id or not value.live(now):
        raise ConnectionError(f"node {server_id} is offline or stale")
    return value


def _plan(
    request: TransferPlanningRequest,
    source: NodeReachability,
    destination: NodeReachability,
    *,
    mode: TransferMode,
    commanded: NodeReachability | None = None,
) -> TransferPlan:
    return TransferPlan(
        mode=mode,
        relay_owner_manager_id=request.relay_owner_manager_id,
        connection_owner_manager_id=(
            commanded.connection_owner_manager_id if commanded else ""
        ),
        source_server_id=request.source_server_id,
        destination_server_id=request.destination_server_id,
        commanded_server_id=commanded.server_id if commanded else "",
        source_data_endpoint=source.data_endpoint,
        source_control_endpoint=source.control_endpoint,
        destination_data_endpoint=destination.data_endpoint,
        destination_control_endpoint=destination.control_endpoint,
        relay_data_endpoint=(
            request.relay_data_endpoint or destination.data_endpoint
        ),
        request_owner_control_endpoint=(
            request.request_owner_control_endpoint
            or destination.control_endpoint
        ),
        connection_owner_control_endpoint=(
            commanded.connection_owner_control_endpoint if commanded else ""
        ),
    )


def plan_transfer(
    request: TransferPlanningRequest,
    *,
    observations: Mapping[str, NodeReachability],
    now: float,
) -> TransferPlan:
    operation = TransferOperation(request.operation)
    relay_id = str(request.relay_owner_manager_id or "").strip()
    source = _live_node(observations, request.source_server_id, now=now)
    destination = _live_node(
        observations, request.destination_server_id, now=now,
    )
    if request.source_server_id == request.destination_server_id == relay_id:
        return _plan(
            request, source, destination, mode=TransferMode.LOCAL,
        )

    if operation is TransferOperation.DOWNLOAD:
        if relay_id in source.reachable_from:
            return _plan(
                request, source, destination, mode=TransferMode.DIRECT_PULL,
            )
        if not source.connection_owner_manager_id:
            raise ConnectionError(
                f"node {source.server_id} has no live control channel"
            )
        return _plan(
            request,
            source,
            destination,
            mode=TransferMode.SOURCE_PUSH,
            commanded=source,
        )

    if relay_id in destination.reachable_from:
        return _plan(
            request, source, destination, mode=TransferMode.DIRECT_PUSH,
        )
    if not destination.connection_owner_manager_id:
        raise ConnectionError(
            f"node {destination.server_id} has no live control channel"
        )
    return _plan(
        request,
        source,
        destination,
        mode=TransferMode.DESTINATION_PULL,
        commanded=destination,
    )
