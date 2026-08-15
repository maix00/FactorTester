from __future__ import annotations

import json
import hashlib
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest

from server.manager.services.server_access import (
    configured_management_access,
    management_access_script_path,
)
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
                "auth": {
                    "provider": "aliyun",
                    "source": "local-keychain",
                    "profile": "ft-public-1",
                    "service": "com.example.aliyun",
                    "account": "ft-public-1",
                    "setup_hint": "先在本机配置管理员凭证",
                },
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
        "auth": {
            "provider": "aliyun",
            "source": "local-keychain",
            "profile": "ft-public-1",
            "service": "com.example.aliyun",
            "account": "ft-public-1",
            "setup_hint": "先在本机配置管理员凭证",
        },
    },)


def test_missing_settings_means_no_guessed_connection_method(tmp_path) -> None:
    assert configured_management_access(tmp_path) == ()


def test_missing_management_access_key_means_no_guessed_connection_method(
    tmp_path,
) -> None:
    (tmp_path / ".settings").write_text(json.dumps({
        "data_dir": str(tmp_path / "data"),
    }), encoding="utf-8")

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


def test_management_access_validates_script_metadata(tmp_path) -> None:
    body = b"#!/bin/sh\nprintf '%s\\n' safe\n"
    (tmp_path / ".settings").write_text(json.dumps({
        "management_access": [{
            "id": "operator-route",
            "kind": "operator-defined",
            "script": {
                "id": "operator-route-v1",
                "filename": "connect.sh",
                "sha256": hashlib.sha256(body).hexdigest(),
                "requires_auth": True,
            },
        }],
    }), encoding="utf-8")

    value = configured_management_access(tmp_path)

    assert value[0]["script"]["id"] == "operator-route-v1"
    assert value[0]["script"]["content_type"] == "text/x-shellscript"


def test_management_access_rejects_script_path_and_invalid_digest(tmp_path) -> None:
    (tmp_path / ".settings").write_text(json.dumps({
        "management_access": [{
            "id": "operator-route",
            "kind": "operator-defined",
            "script": {
                "id": "operator-route-v1",
                "filename": "../connect.sh",
                "sha256": "not-a-digest",
            },
        }],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="script.filename is invalid"):
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


def test_manager_health_route_returns_redacted_runtime_checks(tmp_path) -> None:
    state = manager.ManagerState(tmp_path, "python", server_id="server-1")
    state._sessions[state._token_hash("manager-token")] = (
        "GTHT@MaxJJW@1", "super_admin", float("inf"),
    )
    manager.Handler.state = state
    server = ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/manager/health",
            headers={"Authorization": "Bearer manager-token"},
        )
        with urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert payload["success"] is True
    assert payload["server_id"] == "server-1"
    assert payload["checks"]["manager"]["status"] == "ok"


def test_manager_access_script_route_verifies_and_downloads_declared_asset(tmp_path) -> None:
    body = b"#!/bin/sh\nprintf '%s\\n' safe\n"
    script = {
        "id": "operator-route-v1",
        "filename": "connect.sh",
        "sha256": hashlib.sha256(body).hexdigest(),
        "requires_auth": True,
    }
    settings = tmp_path / ".settings"
    settings.write_text(json.dumps({
        "management_access": [{
            "id": "operator-route",
            "kind": "operator-defined",
            "script": script,
        }],
    }), encoding="utf-8")
    asset = management_access_script_path(tmp_path, script["id"])
    asset.parent.mkdir(parents=True)
    asset.write_bytes(body)

    state = manager.ManagerState(tmp_path, "python", server_id="server-1")
    state.management_access = configured_management_access(tmp_path)
    state._sessions[state._token_hash("manager-token")] = (
        "GTHT@MaxJJW@1", "super_admin", float("inf"),
    )
    manager.Handler.state = state
    server = ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/manager/access/"
            "operator-route/script",
            headers={"Authorization": "Bearer manager-token"},
        )
        with urlopen(request) as response:
            downloaded = response.read()
            assert response.headers["ETag"].strip('"') == script["sha256"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert downloaded == body
