from __future__ import annotations

from server.manager import runtime as manager
from server.manager.storage.control_db import CONTROL_DATABASE_ENV
from server.manager.state.data_plane_process import _client_origins


class _Process:
    pid = 4321

    def poll(self):
        return None


def test_manager_starts_dual_surface_data_plane_without_postgres(
    tmp_path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    state = manager.ManagerState(
        repo,
        "python",
        data_root=tmp_path / "data",
        state_root=tmp_path / "state",
        server_id="node-a",
    )
    state.configure_data_plane(
        client_host="0.0.0.0",
        client_port=7997,
        client_control_endpoint="https://factor.example:7998",
        client_data_endpoint="https://factor.example:7997",
        overlay_bind_address="10.77.0.2",
        peer_port=17997,
    )
    observed: dict[str, object] = {}

    def popen(command, **kwargs):
        observed["command"] = list(command)
        observed["env"] = dict(kwargs["env"])
        return _Process()

    monkeypatch.setattr(state, "_port_is_in_use", lambda _port: False)
    monkeypatch.setattr("server.manager.state.data_plane_process.subprocess.Popen", popen)
    monkeypatch.setenv(CONTROL_DATABASE_ENV, "postgresql://must-not-leak")

    message = state.start_data_plane()

    command = observed["command"]
    environment = observed["env"]
    assert "server.manager.data_plane.app" in command
    assert command[command.index("--client-port") + 1] == "7997"
    assert command[command.index("--overlay-bind-address") + 1] == "10.77.0.2"
    assert command[command.index("--peer-port") + 1] == "17997"
    assert command[command.index("--transfer-database") + 1] == str(
        state.transfer_database_path
    )
    assert command[command.index("--node-key") + 1] == str(
        state.node_identity_path
    )
    assert CONTROL_DATABASE_ENV not in environment
    assert "7997" in message and "17997" in message


def test_peer_data_listener_requires_explicit_wireguard_host(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    state = manager.ManagerState(
        repo,
        "python",
        data_root=tmp_path / "data",
        state_root=tmp_path / "state",
        server_id="node-a",
    )

    try:
        state.configure_data_plane(
            client_host="0.0.0.0",
            client_port=7997,
            client_control_endpoint="http://127.0.0.1:7998",
            client_data_endpoint="http://127.0.0.1:7997",
            overlay_bind_address="0.0.0.0",
            peer_port=17997,
        )
    except ValueError as exc:
        assert "WireGuard" in str(exc) or "private" in str(exc)
    else:  # pragma: no cover - interface isolation invariant
        raise AssertionError("wildcard peer data listener was accepted")


def test_local_client_data_plane_allows_loopback_and_lan_manager_origins(
    monkeypatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_LAN_ADDRESSES", "10.98.181.217")

    origins = _client_origins(
        "http://10.98.181.217:7998",
        public_server=False,
    )

    assert origins[0] == "http://10.98.181.217:7998"
    assert "http://127.0.0.1:7998" in origins
    assert "http://localhost:7998" in origins
    assert "http://10.98.181.217:7998" in origins


def test_public_client_data_plane_keeps_only_configured_origin() -> None:
    assert _client_origins(
        "https://203.0.113.10:7998",
        public_server=True,
    ) == ("https://203.0.113.10:7998",)
