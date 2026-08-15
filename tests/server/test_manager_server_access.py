from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest

from server.manager.services.server_access import configured_management_access
from server.manager import runtime as manager


def test_management_access_is_loaded_from_server_settings(tmp_path) -> None:
    (tmp_path / ".settings").write_text(json.dumps({
        "data_dir": str(tmp_path / "data"),
        "sqlite_db_path": str(tmp_path / "data.sqlite"),
        "management_access": {
            "methods": [{
                "id": "server-provided-route",
                "kind": "operator-defined",
                "label": "由服务器声明",
                "endpoint": "opaque://operator-owned",
                "capabilities": ["inspect", "publish"],
            }],
        },
    }), encoding="utf-8")

    value = configured_management_access(tmp_path)

    assert value == ({
        "id": "server-provided-route",
        "kind": "operator-defined",
        "label": "由服务器声明",
        "endpoint": "opaque://operator-owned",
        "capabilities": ["inspect", "publish"],
    },)


def test_missing_settings_means_no_guessed_connection_method(tmp_path) -> None:
    assert configured_management_access(tmp_path) == ()


def test_management_access_rejects_secrets_and_commands(tmp_path) -> None:
    (tmp_path / ".settings").write_text(json.dumps({
        "management_access": [{
            "id": "unsafe",
            "kind": "operator-defined",
            "command": "do-not-run",
        }],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported fields"):
        configured_management_access(tmp_path)


def test_manager_identity_route_returns_server_owned_access_projection(tmp_path) -> None:
    state = manager.ManagerState(tmp_path, "python", server_id="server-1")
    state.management_access = ({
        "id": "declared-route",
        "kind": "operator-defined",
        "endpoint": "opaque://server-settings",
    },)
    state.data_plane_process_config = SimpleNamespace(
        client_data_endpoint="http://127.0.0.1:7997",
        client_port=7997,
    )
    state.manager_public_endpoint = "http://127.0.0.1:7998"
    state.service_ports = lambda: {7999}
    state._sessions[state._token_hash("manager-token")] = (
        "GTHT@MaxJJW@1", "super_admin", float("inf"),
    )
    manager.Handler.state = state
    server = ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/manager/identity",
            headers={"Authorization": "Bearer manager-token"},
        )
        with urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert payload["server"]["server_id"] == "server-1"
    assert payload["factor_tester"]["data_port"] == 7997
    assert payload["management_access"][0]["id"] == "declared-route"
