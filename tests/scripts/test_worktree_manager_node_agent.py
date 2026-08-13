from __future__ import annotations

import threading
from contextlib import contextmanager

import pytest

from server.manager import runtime as manager
from server.manager.storage.transfers.inbox import TransferInboxStore
from server.manager.transfers.node_agent import NodeAgent
from server.manager.transfers.node_client import NodeControlClient
from server.manager.transfers.node_keys import NodeKey
from server.manager.transfers.node_models import NewNodeCommand


@contextmanager
def _running_manager(state):
    manager.Handler.state = state
    server = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _agent(tmp_path, endpoint: str, *, token: str = "enroll-secret") -> NodeAgent:
    key = NodeKey.load_or_create(tmp_path / "office-a.key", node_id="office-a")
    inbox = TransferInboxStore(
        tmp_path / "node-transfers.sqlite", server_id="office-a",
    )
    return NodeAgent(
        inbox=inbox,
        key=key,
        manager_endpoints=lambda: (endpoint,),
        enrollment_token=token,
        data_endpoint="http://127.0.0.1:7997",
        reachable_from=("office-a",),
    )


def _enqueue(state, *, key: str = "agent-command"):
    return state.node_control_hub.enqueue(NewNodeCommand(
        idempotency_key=key,
        transfer_id="transfer-1",
        attempt_id="attempt-1",
        command_type="source.push",
        target_server_id="office-a",
        payload={"relay_endpoint": "http://public-b1:7997"},
        expires_at=4_000_000_000.0,
    ))


def test_poll_fallback_persists_before_remote_ack(tmp_path) -> None:
    public = manager.ManagerState(
        tmp_path / "public", "python", server_id="public-b1",
    )
    public.federation_registration_token = "enroll-secret"
    command = _enqueue(public)

    with _running_manager(public) as endpoint:
        agent = _agent(tmp_path, endpoint)
        agent.enroll()
        received = agent.poll_once(timeout=0)

    assert [item.command_id for item in received] == [command.command_id]
    assert agent.inbox.claim(claimant="executor", now=1_000_000_000.0)[
        0
    ].command_id == command.command_id
    assert public.node_commands.pending(node_id="office-a") == []


def test_ack_failure_replays_same_local_inbox_record(tmp_path, monkeypatch) -> None:
    public = manager.ManagerState(
        tmp_path / "public", "python", server_id="public-b1",
    )
    public.federation_registration_token = "enroll-secret"
    command = _enqueue(public)

    with _running_manager(public) as endpoint:
        agent = _agent(tmp_path, endpoint)
        agent.enroll()
        original = NodeControlClient.acknowledge
        calls = 0

        def fail_once(client, command_id):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ConnectionError("simulated lost ACK")
            return original(client, command_id)

        monkeypatch.setattr(NodeControlClient, "acknowledge", fail_once)
        with pytest.raises(ConnectionError, match="lost ACK"):
            agent.poll_once(timeout=0)
        replayed = agent.poll_once(timeout=0)

    assert replayed[0].command_id == command.command_id
    assert agent.inbox.latest_sequence() == command.sequence
    assert public.node_commands.pending(node_id="office-a") == []


def test_sse_once_receives_persists_and_acknowledges_command(tmp_path) -> None:
    public = manager.ManagerState(
        tmp_path / "public", "python", server_id="public-b1",
    )
    public.federation_registration_token = "enroll-secret"
    command = _enqueue(public, key="sse-agent-command")

    with _running_manager(public) as endpoint:
        agent = _agent(tmp_path, endpoint)
        agent.enroll()
        received = agent.stream_once(max_commands=1)

    assert [item.command_id for item in received] == [command.command_id]
    assert agent.inbox.latest_sequence() == command.sequence
    assert public.node_commands.pending(node_id="office-a") == []


def test_agent_uses_only_one_healthy_endpoint_per_cycle(tmp_path) -> None:
    public = manager.ManagerState(
        tmp_path / "public", "python", server_id="public-b1",
    )
    public.federation_registration_token = "enroll-secret"
    _enqueue(public)

    with _running_manager(public) as endpoint:
        agent = _agent(tmp_path, endpoint)
        agent.manager_endpoints = lambda: (
            "http://127.0.0.1:1",
            endpoint,
        )
        received = agent.poll_healthy_once(timeout=0)

    assert len(received) == 1
    assert agent.active_manager_endpoint == endpoint
