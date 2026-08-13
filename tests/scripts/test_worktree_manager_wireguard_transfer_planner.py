from __future__ import annotations

import pytest

from server.manager.transfers.models import TransferMode, TransferOperation
from server.manager.transfers.planner import (
    NodeEndpoint,
    NodeUnavailable,
    TransferPlanningRequest,
    plan_transfer,
)


def _node(server_id: str, octet: int, *, online: bool = True) -> NodeEndpoint:
    return NodeEndpoint(
        server_id=server_id,
        peer_data_endpoint=f"http://10.77.0.{octet}:17997",
        peer_control_endpoint=f"http://10.77.0.{octet}:17998",
        observed_at=100.0,
        expires_at=130.0,
        online=online,
    )


def _request(operation: TransferOperation) -> TransferPlanningRequest:
    download = operation is TransferOperation.DOWNLOAD
    return TransferPlanningRequest(
        operation=operation,
        request_owner_manager_id="node-b",
        source_server_id="node-a" if download else "node-b",
        destination_server_id="node-b" if download else "node-a",
        storage_server_id="node-a",
        client_data_endpoint="https://factor.example:7997",
    )


@pytest.mark.parametrize(
    ("operation", "mode", "source_octet", "destination_octet"),
    [
        (TransferOperation.DOWNLOAD, TransferMode.DIRECT_PULL, 1, 2),
        (TransferOperation.UPLOAD, TransferMode.DIRECT_PUSH, 2, 1),
    ],
)
def test_plan_separates_public_client_and_wireguard_peer_endpoints(
    operation: TransferOperation,
    mode: TransferMode,
    source_octet: int,
    destination_octet: int,
) -> None:
    plan = plan_transfer(
        _request(operation),
        endpoints={"node-a": _node("node-a", 1), "node-b": _node("node-b", 2)},
        now=101.0,
    )

    assert plan.mode is mode
    assert plan.client_data_endpoint == "https://factor.example:7997"
    assert plan.source_peer_data_endpoint == (
        f"http://10.77.0.{source_octet}:17997"
    )
    assert plan.destination_peer_data_endpoint == (
        f"http://10.77.0.{destination_octet}:17997"
    )
    assert plan.source_peer_control_endpoint == (
        f"http://10.77.0.{source_octet}:17998"
    )
    assert plan.destination_peer_control_endpoint == (
        f"http://10.77.0.{destination_octet}:17998"
    )


def test_missing_peer_endpoint_is_explicitly_node_unreachable() -> None:
    broken = _node("node-a", 1)
    broken = NodeEndpoint(
        server_id=broken.server_id,
        peer_data_endpoint="",
        peer_control_endpoint=broken.peer_control_endpoint,
        observed_at=broken.observed_at,
        expires_at=broken.expires_at,
        online=True,
    )

    with pytest.raises(NodeUnavailable) as denied:
        plan_transfer(
            _request(TransferOperation.DOWNLOAD),
            endpoints={"node-a": broken, "node-b": _node("node-b", 2)},
            now=101.0,
        )

    assert denied.value.code == "node_unreachable"
    assert denied.value.server_id == "node-a"


def test_local_plan_keeps_public_entry_but_freezes_private_self_route() -> None:
    request = TransferPlanningRequest(
        operation=TransferOperation.DOWNLOAD,
        request_owner_manager_id="node-b",
        source_server_id="node-b",
        destination_server_id="node-b",
        storage_server_id="node-b",
        client_data_endpoint="https://factor.example:7997",
    )

    plan = plan_transfer(
        request,
        endpoints={"node-b": _node("node-b", 2)},
        now=101.0,
    )

    assert plan.mode is TransferMode.LOCAL
    assert plan.client_data_endpoint.endswith(":7997")
    assert plan.source_peer_data_endpoint.endswith(":17997")
