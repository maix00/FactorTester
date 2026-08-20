from __future__ import annotations

import threading

from server.manager.domain.federation import ServiceRoute
from server.manager.domain.federation.capability_catalog import (
    load_peer_capability_snapshots,
)


def _route(server_id: str) -> ServiceRoute:
    return ServiceRoute(
        server_id=server_id,
        role="peer",
        branch="main",
        revision="test",
        port=7998,
        endpoint=f"http://{server_id}:7998",
        online=True,
    )


def test_peer_capability_catalog_loads_servers_concurrently() -> None:
    entered = threading.Barrier(3)

    def load(route: ServiceRoute) -> dict[str, object]:
        entered.wait(timeout=1)
        return {"server_id": route.server_id}

    result = load_peer_capability_snapshots(
        [_route("peer-a"), _route("peer-b"), _route("peer-c")], load,
    )

    assert set(result) == {"peer-a", "peer-b", "peer-c"}


def test_peer_capability_catalog_isolates_one_failed_server() -> None:
    def load(route: ServiceRoute) -> dict[str, object]:
        if route.server_id == "peer-b":
            raise ConnectionError("offline")
        return {"server_id": route.server_id}

    result = load_peer_capability_snapshots(
        [_route("peer-a"), _route("peer-b")], load,
    )

    assert result["peer-a"] == {"server_id": "peer-a"}
    assert result["peer-b"] is None
