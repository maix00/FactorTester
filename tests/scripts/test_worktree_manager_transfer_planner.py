from __future__ import annotations

import pytest

from server.manager.transfers.planner import (
    NodeReachability,
    TransferPlanningRequest,
    plan_transfer,
)
from server.manager.transfers.models import TransferMode, TransferOperation


def _node(
    server_id: str,
    *,
    reachable_from: tuple[str, ...] = (),
    connection_owner: str = "",
    online: bool = True,
) -> NodeReachability:
    return NodeReachability(
        server_id=server_id,
        data_endpoint=f"https://{server_id}:7997",
        reachable_from=frozenset(reachable_from),
        connection_owner_manager_id=connection_owner,
        observed_at=100.0,
        expires_at=130.0,
        online=online,
    )


def _request(
    operation: TransferOperation,
    *,
    source: str,
    destination: str,
) -> TransferPlanningRequest:
    return TransferPlanningRequest(
        operation=operation,
        relay_owner_manager_id="public-b2",
        source_server_id=source,
        destination_server_id=destination,
        storage_server_id=source,
    )


def test_download_prefers_local_then_direct_pull() -> None:
    local = plan_transfer(
        _request(
            TransferOperation.DOWNLOAD,
            source="public-b2",
            destination="public-b2",
        ),
        observations={"public-b2": _node("public-b2")},
        now=101.0,
    )
    direct = plan_transfer(
        _request(
            TransferOperation.DOWNLOAD,
            source="public-b1",
            destination="public-b2",
        ),
        observations={
            "public-b1": _node(
                "public-b1", reachable_from=("public-b2",),
            ),
            "public-b2": _node("public-b2"),
        },
        now=101.0,
    )

    assert local.mode is TransferMode.LOCAL
    assert direct.mode is TransferMode.DIRECT_PULL
    assert direct.connection_owner_manager_id == ""
    assert direct.hop_budget == 1


def test_unreachable_download_source_is_commanded_to_push() -> None:
    planned = plan_transfer(
        _request(
            TransferOperation.DOWNLOAD,
            source="office-a",
            destination="public-b2",
        ),
        observations={
            "office-a": _node(
                "office-a", connection_owner="public-b1",
            ),
            "public-b2": _node("public-b2"),
        },
        now=101.0,
    )

    assert planned.mode is TransferMode.SOURCE_PUSH
    assert planned.commanded_server_id == "office-a"
    assert planned.connection_owner_manager_id == "public-b1"


def test_upload_uses_direct_push_or_destination_pull() -> None:
    direct = plan_transfer(
        _request(
            TransferOperation.UPLOAD,
            source="public-b2",
            destination="public-b3",
        ),
        observations={
            "public-b2": _node("public-b2"),
            "public-b3": _node(
                "public-b3", reachable_from=("public-b2",),
            ),
        },
        now=101.0,
    )
    pulled = plan_transfer(
        _request(
            TransferOperation.UPLOAD,
            source="public-b2",
            destination="office-a",
        ),
        observations={
            "public-b2": _node("public-b2"),
            "office-a": _node(
                "office-a", connection_owner="public-b1",
            ),
        },
        now=101.0,
    )

    assert direct.mode is TransferMode.DIRECT_PUSH
    assert pulled.mode is TransferMode.DESTINATION_PULL
    assert pulled.commanded_server_id == "office-a"
    assert pulled.connection_owner_manager_id == "public-b1"


@pytest.mark.parametrize("expired,online", [(True, True), (False, False)])
def test_missing_stale_or_offline_commanded_node_fails_explicitly(
    expired: bool,
    online: bool,
) -> None:
    node = _node("office-a", connection_owner="public-b1", online=online)
    if expired:
        node = NodeReachability(
            server_id=node.server_id,
            data_endpoint=node.data_endpoint,
            reachable_from=node.reachable_from,
            connection_owner_manager_id=node.connection_owner_manager_id,
            observed_at=50.0,
            expires_at=90.0,
            online=node.online,
        )

    with pytest.raises(ConnectionError, match="offline or stale"):
        plan_transfer(
            _request(
                TransferOperation.DOWNLOAD,
                source="office-a",
                destination="public-b2",
            ),
            observations={
                "office-a": node,
                "public-b2": _node("public-b2"),
            },
            now=101.0,
        )


def test_unreachable_node_without_control_owner_is_not_guessed() -> None:
    with pytest.raises(ConnectionError, match="control channel"):
        plan_transfer(
            _request(
                TransferOperation.DOWNLOAD,
                source="office-a",
                destination="public-b2",
            ),
            observations={
                "office-a": _node("office-a"),
                "public-b2": _node("public-b2"),
            },
            now=101.0,
        )
