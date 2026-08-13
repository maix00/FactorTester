from __future__ import annotations

import pytest

from server.manager.storage.transfers.node_presence import NodePresenceStore


def test_presence_is_persistent_authenticated_and_expires(tmp_path) -> None:
    path = tmp_path / "transfers.sqlite"
    store = NodePresenceStore(path, server_id="public-b1")
    store.observe(
        node_id="office-a",
        connection_owner_manager_id="public-b1",
        connection_id="connection-1",
        data_endpoint="http://office-a:7997",
        reachable_from=("office-a",),
        ttl=30.0,
        now=100.0,
    )

    restarted = NodePresenceStore(path, server_id="public-b1")
    live = restarted.require_live("office-a", now=120.0)
    stale = restarted.get("office-a", now=131.0)

    assert live.reachable_from == frozenset({"office-a"})
    assert stale is not None and not stale.online
    with pytest.raises(ConnectionError, match="offline or stale"):
        restarted.require_live("office-a", now=131.0)


def test_stale_connection_cannot_overwrite_or_disconnect_new_owner(tmp_path) -> None:
    store = NodePresenceStore(
        tmp_path / "transfers.sqlite", server_id="public-b1",
    )
    store.observe(
        node_id="office-a",
        connection_owner_manager_id="public-b1",
        connection_id="new",
        data_endpoint="http://office-a:7997",
        reachable_from=(),
        ttl=30.0,
        now=110.0,
    )

    changed = store.mark_offline(
        node_id="office-a", connection_id="old", now=111.0,
    )
    assert changed is False
    assert store.require_live("office-a", now=112.0).connection_id == "new"

    assert store.mark_offline(
        node_id="office-a", connection_id="new", now=113.0,
    ) is True
