from __future__ import annotations

import threading
import time

from server.manager.storage.transfers.node_commands import NodeCommandQueue
from server.manager.storage.transfers.node_presence import NodePresenceStore
from server.manager.transfers.node_hub import NodeControlHub
from server.manager.transfers.node_models import NewNodeCommand


def _command(
    *,
    key: str = "transfer-1:attempt-1:source-push",
    expires_at: float = 200.0,
) -> NewNodeCommand:
    return NewNodeCommand(
        idempotency_key=key,
        transfer_id="transfer-1",
        attempt_id="attempt-1",
        command_type="source.push",
        target_server_id="office-a",
        payload={"relay_endpoint": "https://public-b2:7997"},
        expires_at=expires_at,
    )


def test_public_command_queue_replays_until_authenticated_node_acknowledges(
    tmp_path,
) -> None:
    path = tmp_path / "transfers.sqlite"
    queue = NodeCommandQueue(path, server_id="public-b1")

    first = queue.enqueue(_command(), now=100.0)
    duplicate = NodeCommandQueue(path, server_id="public-b1").enqueue(
        _command(), now=101.0,
    )
    initial = queue.pending(node_id="office-a", after_sequence=0, now=102.0)
    replay = queue.pending(
        node_id="office-a", after_sequence=first.sequence, now=103.0,
    )

    assert duplicate == first
    assert initial == [first]
    assert replay == [first]
    queue.acknowledge(
        first.command_id, node_id="office-a", now=104.0,
    )
    assert queue.pending(node_id="office-a", after_sequence=0, now=105.0) == []


def test_command_ack_is_target_bound_and_sequence_is_per_node(tmp_path) -> None:
    queue = NodeCommandQueue(
        tmp_path / "transfers.sqlite", server_id="public-b1",
    )
    first = queue.enqueue(_command(key="one"), now=100.0)
    second = queue.enqueue(_command(key="two"), now=101.0)
    peer = queue.enqueue(NewNodeCommand(
        idempotency_key="peer-one",
        transfer_id="transfer-2",
        attempt_id="attempt-2",
        command_type="destination.pull",
        target_server_id="office-b",
        payload={},
        expires_at=200.0,
    ), now=102.0)

    assert (first.sequence, second.sequence, peer.sequence) == (1, 2, 1)
    try:
        queue.acknowledge(
            first.command_id, node_id="office-b", now=103.0,
        )
    except PermissionError as exc:
        assert "target" in str(exc)
    else:  # pragma: no cover - explicit security assertion
        raise AssertionError("another node acknowledged the command")


def test_hub_reconnect_replaces_previous_connection_and_updates_presence(
    tmp_path,
) -> None:
    path = tmp_path / "transfers.sqlite"
    queue = NodeCommandQueue(path, server_id="public-b1")
    presence = NodePresenceStore(path, server_id="public-b1")
    hub = NodeControlHub(
        queue,
        presence,
        manager_id="public-b1",
        presence_ttl=30.0,
    )

    first = hub.attach(
        node_id="office-a",
        data_endpoint="http://office-a:7997",
        reachable_from=(),
        now=100.0,
    )
    second = hub.attach(
        node_id="office-a",
        data_endpoint="http://office-a:7997",
        reachable_from=(),
        now=101.0,
    )

    assert not hub.is_current(first)
    assert hub.is_current(second)
    observation = presence.require_live("office-a", now=102.0)
    assert observation.connection_owner_manager_id == "public-b1"
    assert observation.connection_id == second.connection_id

    hub.detach(first, now=103.0)
    assert presence.require_live("office-a", now=104.0).online
    hub.detach(second, now=105.0)
    assert not presence.get("office-a", now=106.0).online


def test_long_poll_wakes_from_same_durable_queue(tmp_path) -> None:
    path = tmp_path / "transfers.sqlite"
    queue = NodeCommandQueue(path, server_id="public-b1")
    hub = NodeControlHub(
        queue,
        NodePresenceStore(path, server_id="public-b1"),
        manager_id="public-b1",
    )
    result: list[object] = []

    thread = threading.Thread(
        target=lambda: result.extend(hub.poll(
            node_id="office-a",
            after_sequence=0,
            timeout=1.0,
            now=time.time,
        )),
        daemon=True,
    )
    thread.start()
    time.sleep(0.03)
    current = time.time()
    hub.enqueue(_command(expires_at=current + 60.0), now=current)
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert len(result) == 1
