from __future__ import annotations

import os
import hashlib
import json
import sqlite3
import signal
import socket
import sys
import threading
import base64
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

import pytest

from server.manager import app as manager_app
from server.manager import runtime as manager
from server.manager.data_plane.context import DataPlaneRuntime
from server.manager.data_plane.server import ClientDataPlaneHTTPServer
from server.manager.objects.adapters.public_research import (
    PublicResearchOriginAdapter,
)
from server.manager.objects.origin import ObjectOriginRegistry
from tools.cli.release.research_reporting.public_research.library import PublicResearchLibrary
from tools.cli.release.research_reporting.public_research.object_store import (
    PublicResearchObjectStore,
)


class _Process:
    next_pid = 100

    def __init__(self, command):
        type(self).next_pid += 1
        self.pid = type(self).next_pid
        self.command = list(command)
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return 0


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


@contextmanager
def _running_research_data_plane(state):
    store = PublicResearchObjectStore(state.public_research)
    runtime = DataPlaneRuntime(
        server_id=state.server_id,
        transfer_database=state.transfer_database_path,
        staging_root=state.transfer_submission_root,
        origin_resolver=ObjectOriginRegistry(
            adapters={
                "research_asset": PublicResearchOriginAdapter(store),
                "research_attachment": PublicResearchOriginAdapter(store),
                "research_local_resource": PublicResearchOriginAdapter(store),
            },
            fallback=lambda _transfer: (_ for _ in ()).throw(
                FileNotFoundError("research object only")
            ),
        ),
    )
    server = ClientDataPlaneHTTPServer(("127.0.0.1", 0), runtime=runtime)
    endpoint = f"http://127.0.0.1:{server.server_address[1]}"
    state.configure_data_plane(
        client_host="127.0.0.1",
        client_port=server.server_address[1],
        client_control_endpoint="http://127.0.0.1:7998",
        client_data_endpoint=endpoint,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield endpoint
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@contextmanager
def _running_dual_loopback_manager(state):
    """Run the same handler on IPv4 and IPv6 loopback for localhost tests."""
    manager.Handler.state = state
    ipv4 = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
    port = ipv4.server_address[1]
    if not socket.has_ipv6:
        ipv4.server_close()
        pytest.skip("IPv6 is unavailable on this test host")
    try:
        ipv6 = manager.IPv6LoopbackHTTPServer(("::1", port), manager.Handler)
    except OSError as error:
        ipv4.server_close()
        pytest.skip(f"IPv6 loopback cannot bind: {error}")
    threads = [
        threading.Thread(target=server.serve_forever, daemon=True)
        for server in (ipv4, ipv6)
    ]
    for thread in threads:
        thread.start()
    try:
        yield port
    finally:
        for server in (ipv6, ipv4):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)


def test_manager_binds_all_interfaces_for_lan_web_by_default(
    tmp_path, monkeypatch, capsys
) -> None:
    observed = {"events": []}

    class _Server:
        def __init__(self, address, handler):
            observed["address"] = address
            observed["events"].append("bind")

        def serve_forever(self):
            observed["events"].append("serve")
            return None

        def server_close(self):
            return None

    monkeypatch.setattr(manager, "ThreadingHTTPServer", _Server)
    monkeypatch.setattr(manager.ManagerState, "stop_all", lambda self: None)
    monkeypatch.setattr(manager.ManagerState, "start_configured_federation", lambda self: None)
    monkeypatch.setattr(manager.ManagerState, "cleanup_detached_worktrees", lambda self: [])
    monkeypatch.setattr(
        manager.ManagerState,
        "local_internal_addresses",
        lambda self: ["192.168.50.10"],
    )
    monkeypatch.setattr(
        manager.ManagerState,
        "start_data_plane",
        lambda self: observed["events"].append("artifact") or "artifact",
    )
    monkeypatch.setattr(manager_app.webbrowser, "open", lambda _url: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["server.manager.app", "--repo", str(tmp_path), "--no-browser"],
    )

    assert manager_app.main(runtime_module=manager) == 0
    assert observed["address"] == ("0.0.0.0", 7998)
    assert observed["events"] == ["bind", "artifact", "serve"]
    output = capsys.readouterr().out
    assert "局域网访问: http://192.168.50.10:7998/" in output
    assert "172.18." not in output
    assert "127.0.0.1" not in output


def test_manager_sigterm_runs_child_process_cleanup(tmp_path, monkeypatch) -> None:
    observed = {"events": [], "handler": None}
    previous_handler = object()

    class _Server:
        def __init__(self, _address, _handler):
            observed["events"].append("bind")

        def serve_forever(self):
            observed["events"].append("serve")
            observed["handler"](signal.SIGTERM, None)

        def server_close(self):
            observed["events"].append("close")

    def set_signal(signum, handler):
        assert signum == signal.SIGTERM
        if handler is previous_handler:
            observed["events"].append("restore-sigterm")
        else:
            observed["handler"] = handler
            observed["events"].append("install-sigterm")
        return previous_handler

    monkeypatch.setattr(manager, "ThreadingHTTPServer", _Server)
    monkeypatch.setattr(
        manager.ManagerState,
        "stop_all",
        lambda self: observed["events"].append("stop-all"),
    )
    monkeypatch.setattr(
        manager.ManagerState, "start_configured_federation", lambda self: None,
    )
    monkeypatch.setattr(
        manager.ManagerState, "cleanup_detached_worktrees", lambda self: [],
    )
    monkeypatch.setattr(
        manager.ManagerState,
        "start_data_plane",
        lambda self: "artifact",
    )
    monkeypatch.setattr(manager_app.signal, "signal", set_signal)

    assert manager_app.main([
        "--repo", str(tmp_path),
        "--host", "192.0.2.1",
        "--no-browser",
    ], runtime_module=manager) == 0
    assert observed["events"] == [
        "bind",
        "install-sigterm",
        "serve",
        "stop-all",
        "close",
        "restore-sigterm",
    ]


def test_manager_serves_localhost_over_ipv6(tmp_path, monkeypatch) -> None:
    state = manager.ManagerState(tmp_path, "python")
    monkeypatch.setattr(state, "worktrees", lambda: [])

    with _running_dual_loopback_manager(state) as port:
        with urlopen(f"http://[::1]:{port}/") as response:
            assert response.status == 200
            assert b"<title>FTClient</title>" in response.read()


def test_direct_remote_client_cannot_spoof_loopback_forwarded_address() -> None:
    handler = object.__new__(manager.Handler)
    handler.client_address = ("10.98.184.25", 51234)
    handler.headers = {"X-Forwarded-For": "127.0.0.1"}

    assert not handler._is_loopback_client()


def test_loopback_reverse_proxy_can_forward_original_client_address() -> None:
    handler = object.__new__(manager.Handler)
    handler.client_address = ("127.0.0.1", 51234)
    handler.headers = {"X-Forwarded-For": "10.98.184.25"}

    assert not handler._is_loopback_client()


def test_configured_docker_gateway_forwards_one_canonical_client_address(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv(
        "FACTORTESTER_TRUSTED_PROXY_CIDRS", "172.30.186.1/32",
    )
    state = manager.ManagerState(tmp_path, "python")
    handler = object.__new__(manager.Handler)
    handler.state = state
    handler.client_address = ("172.30.186.1", 51234)
    handler.headers = {
        "X-Forwarded-For": "2001:b030:8150:ff07::5",
        "X-Forwarded-Proto": "https",
        "User-Agent": "FactorTester-Swift/1.2",
    }

    assert handler._client_ip() == manager.ipaddress.ip_address(
        "2001:b030:8150:ff07::5"
    )
    assert not handler._is_private_lan_client()
    assert handler._is_https_proxy_request()
    assert handler._device_request_metadata() == {
        "client_type": "swift",
        "client_name": "FactorTester Swift 1.2",
        "enrollment_ip": "2001:b030:8150:ff07::5",
    }


def test_configured_local_docker_gateway_accepts_factor_client(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_LOCAL_CLIENT_CIDRS", "172.18.0.1/32")
    state = manager.ManagerState(tmp_path, "python", server_id="local")
    handler = object.__new__(manager.Handler)
    handler.state = state
    handler.client_address = ("172.18.0.1", 51234)
    handler.headers = {"X-FactorTester-Client": "cli"}

    assert handler._is_local_ftclient()

    handler.headers = {}
    assert not handler._is_local_ftclient()

    handler.client_address = ("172.18.0.9", 51234)
    handler.headers = {"X-FactorTester-Client": "cli"}
    assert not handler._is_local_ftclient()

    state.public_server = True
    handler.client_address = ("172.18.0.1", 51234)
    assert not handler._is_local_ftclient()


def test_untrusted_docker_gateway_cannot_spoof_forwarded_metadata(
    tmp_path,
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    handler = object.__new__(manager.Handler)
    handler.state = state
    handler.client_address = ("172.30.186.1", 51234)
    handler.headers = {
        "X-Forwarded-For": "8.8.8.8",
        "X-Forwarded-Proto": "https",
    }

    assert handler._client_ip() == manager.ipaddress.ip_address("172.30.186.1")
    assert handler._is_private_lan_client()
    assert not handler._is_https_proxy_request()


def test_trusted_proxy_rejects_ambiguous_forwarded_address_chain(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv(
        "FACTORTESTER_TRUSTED_PROXY_CIDRS", "172.30.186.1/32",
    )
    state = manager.ManagerState(tmp_path, "python")
    handler = object.__new__(manager.Handler)
    handler.state = state
    handler.client_address = ("172.30.186.1", 51234)
    handler.headers = {
        "X-Forwarded-For": "127.0.0.1, 8.8.8.8",
        "X-Forwarded-Proto": "https, http",
    }

    assert handler._client_ip() == manager.ipaddress.ip_address("172.30.186.1")
    assert not handler._is_https_proxy_request()


def test_invalid_trusted_proxy_configuration_fails_closed(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv(
        "FACTORTESTER_TRUSTED_PROXY_CIDRS",
        "172.30.186.1/32,not-a-network",
    )

    with pytest.raises(
        ValueError, match="FACTORTESTER_TRUSTED_PROXY_CIDRS",
    ):
        manager.ManagerState(tmp_path, "python")


def test_public_network_info_stays_private_behind_loopback_proxy(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_REQUIRE_LOGIN_FOR_UI", "1")
    monkeypatch.setenv("FACTORTESTER_REQUIRE_DEVICE_AUTH", "1")
    monkeypatch.setenv("FACTORTESTER_PUBLIC_SERVER", "1")
    state = manager.ManagerState(tmp_path, "python", server_id="public-main")

    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/api/server/network-info",
            headers={
                "X-Forwarded-For": "2001:b030:8150:ff07::5",
                "X-Forwarded-Proto": "https",
            },
        )
        with pytest.raises(HTTPError) as denied:
            urlopen(request)

        swift_request = Request(
            f"{base_url}/api/server/network-info",
            headers={
                "X-Forwarded-For": "2001:b030:8150:ff07::5",
                "X-Forwarded-Proto": "https",
                "X-FactorTester-Client": "swift",
            },
        )
        with urlopen(swift_request) as response:
            payload = json.loads(response.read())

    assert denied.value.code == 401
    assert payload["success"] is True


def test_worktree_api_requires_shared_bearer_token(tmp_path, monkeypatch) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.parent.mkdir(parents=True, exist_ok=True)
    state.capability_path.write_text(
        "test-capability", encoding="ascii"
    )
    monkeypatch.setattr(state, "worktrees", lambda: [])

    with _running_manager(state) as base_url:
        with pytest.raises(HTTPError) as denied:
            urlopen(f"{base_url}/api/worktrees")
        assert denied.value.code == 401

        request = Request(
            f"{base_url}/api/worktrees",
            headers={"Authorization": "Bearer test-capability"},
        )
        with urlopen(request) as response:
            assert response.status == 200


def test_manager_login_issues_ui_session_for_api_access(
    tmp_path, monkeypatch
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("internal-capability", encoding="ascii")
    monkeypatch.setattr(state, "worktrees", lambda: [])
    monkeypatch.setattr(
        manager,
        "_authenticate_user",
        lambda username, password: (
            ("root@1", "super_admin")
            if (username, password) == ("root", "secret")
            else (_ for _ in ()).throw(PermissionError("invalid"))
        ),
    )
    monkeypatch.setattr(state, "_alias_for_principal", lambda _principal: "MaxJJW")

    with _running_manager(state) as base_url:
        login = Request(
            f"{base_url}/auth/login",
            data=json.dumps({
                "username": "root",
                "password": "secret",
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(login) as response:
            session = json.loads(response.read())
            cookie = response.headers["Set-Cookie"]
        request = Request(
            f"{base_url}/api/worktrees",
            headers={"Authorization": f"Bearer {session['token']}"},
        )
        with urlopen(request) as response:
            assert response.status == 200
            refreshed_cookie = response.headers["Set-Cookie"]

    assert session["username"] == "root@1"
    assert session["alias"] == "MaxJJW"
    assert session["role"] == "super_admin"
    assert session["expires_in"] == manager.MANAGER_SESSION_TTL_SECONDS
    assert f"Max-Age={30 * 24 * 60 * 60}" in cookie
    assert f"Max-Age={30 * 24 * 60 * 60}" in refreshed_cookie


def test_manager_login_returns_json_when_authentication_crashes(
    tmp_path, monkeypatch
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    monkeypatch.setattr(
        manager,
        "_authenticate_user",
        lambda _username, _password: (_ for _ in ()).throw(
            RuntimeError("authentication dependency unavailable")
        ),
    )

    with _running_manager(state) as base_url:
        login = Request(
            f"{base_url}/auth/login",
            data=b'{"username":"root","password":"secret"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as failed:
            urlopen(login)

    assert failed.value.code == 500
    assert json.loads(failed.value.read()) == {
        "success": False,
        "error": "manager login failed",
    }


def test_job_detail_uses_worker_but_artifact_metadata_uses_manager_repository(
    tmp_path, monkeypatch
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state._sessions[state._token_hash("user-token")] = (
        "user@1", "user", float("inf"),
    )
    monkeypatch.setattr(state, "service_ports", lambda: [8141])
    calls = []

    def request(**values):
        calls.append(values)
        return manager.GatewayResponse(
            status=200,
            body=b'{"success":true,"job_id":"job-1"}',
            content_type="application/json",
        )

    monkeypatch.setattr(state.gateway, "request", request)
    monkeypatch.setattr(
        "server.manager.http.job_transfer_routes.JobArtifactCatalog.list",
        lambda _catalog, **_values: [{
            "name": "curve.svg", "file_name": "curve.svg",
            "state": "active", "artifact_role": "output",
        }],
    )
    headers = {"Authorization": "Bearer user-token"}
    with _running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/jobs/job-1?port=8141", headers=headers,
        )) as response:
            detail = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/jobs/job-1/artifacts?port=8141",
            headers=headers,
        )) as response:
            artifacts = json.loads(response.read())

    assert detail["job_id"] == "job-1"
    assert detail["port"] == 8141
    assert artifacts["artifacts"][0]["name"] == "curve.svg"
    assert [item["path"] for item in calls] == ["/api/jobs/job-1"]
    assert all(item["principal"] == "user@1" for item in calls)


@pytest.mark.parametrize(("suffix", "service_path"), [
    ("group-detail", "/get_group_detail"),
    ("group-ranking-detail", "/get_group_ranking_detail"),
    ("group-snapshot", "/get_group_snapshot"),
    ("group-order-flow", "/get_group_order_flow"),
])
def test_job_analysis_routes_use_the_job_origin_and_freeze_job_id(
    tmp_path, monkeypatch, suffix, service_path,
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state._sessions[state._token_hash("user-token")] = (
        "user@1", "user", float("inf"),
    )
    monkeypatch.setattr(state, "service_ports", lambda: [8141, 8180])
    calls = []

    def request(**values):
        calls.append(values)
        return manager.GatewayResponse(
            status=200,
            body=b'{"success":true}',
            content_type="application/json",
        )

    monkeypatch.setattr(state.gateway, "request", request)
    headers = {
        "Authorization": "Bearer user-token",
        "Content-Type": "application/json",
    }
    with _running_manager(state) as base_url:
        request_value = Request(
            f"{base_url}/api/jobs/job-1/{suffix}?port=8180",
            data=b'{"job_id":"wrong","group_index":2}',
            headers=headers,
            method="POST",
        )
        with urlopen(request_value) as response:
            payload = json.loads(response.read())

    assert payload == {"success": True, "port": 8180}
    assert len(calls) == 1
    assert calls[0]["port"] == 8180
    assert calls[0]["path"] == service_path
    assert calls[0]["principal"] == "user@1"
    assert calls[0]["method"] == "POST"
    assert json.loads(calls[0]["body"]) == {
        "job_id": "job-1", "group_index": 2,
    }


def test_manager_rejects_obsolete_artifact_byte_routes(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    monkeypatch.setattr(state, "service_ports", lambda: [8141])
    monkeypatch.setattr(
        state.gateway,
        "request",
        lambda **_values: pytest.fail("obsolete byte route reached service port"),
    )
    with _running_manager(state) as base_url:
        for suffix in (
            "equity_curve_report",
            "equity_curve_report/preview",
            "archive",
        ):
            with pytest.raises(HTTPError) as denied:
                urlopen(f"{base_url}/api/jobs/job-1/artifacts/{suffix}")
            assert denied.value.code == 404


def test_job_detail_tries_cached_origin_before_running_ports(tmp_path, monkeypatch) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.job_index.upsert("user@1", [{
        "job_id": "job-cached", "port": 8999, "updated_at": "2026-08-06T00:00:00Z",
    }])
    monkeypatch.setattr(state, "service_ports", lambda: [8141])
    handler = object.__new__(manager.Handler)
    handler.state = state

    ports = handler._job_ports(
        urlparse("/api/jobs/job-cached?port=8141"), "user@1",
    )

    assert ports == [8999, 8141]


def test_public_jobs_use_one_service_database_page(tmp_path, monkeypatch) -> None:
    state = manager.ManagerState(tmp_path, "python")
    calls = []

    monkeypatch.setattr(state, "preferred_service_port", lambda: 8141)

    def service_json(port, path, principal):
        calls.append((port, path, principal))
        return {
            "jobs": [{"job_id": "job-public", "updated_at": 2.0}],
            "page_size": 1,
            "has_more": True,
            "next_cursor": "cursor-next",
        }

    monkeypatch.setattr(state, "service_json", service_json)
    payload = state.aggregate_public_jobs(cursor="cursor-before", limit=20)

    assert payload["jobs"][0]["job_id"] == "job-public"
    assert payload["jobs"][0]["updated_at"] == 2.0
    assert payload["jobs"][0]["port"] == 8141
    assert payload["jobs"][0]["server_id"] == state.server_id
    assert payload["has_more"] is False
    assert payload["next_cursor"] is None
    assert payload["total"] == 1
    assert calls == [(
        8141,
        "/api/jobs?scope=server&limit=20",
        "__public_jobs__",
    )]


def test_local_projection_indexes_public_and_owner_views_from_one_snapshot(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(tmp_path, "python", server_id="local-feat")
    monkeypatch.setattr(state, "service_ports", lambda: [8141])
    monkeypatch.setattr(
        state,
        "service_json",
        lambda port, path, principal: {
            "jobs": [{
                "job_id": "job-owner",
                "owner": "alice@1",
                "port": port,
                "updated_at": 2.0,
            }],
        },
    )

    state.refresh_local_job_projection()

    assert state.job_index.list("__public_jobs__")[0]["job_id"] == "job-owner"
    assert state.job_index.list("alice@1")[0]["job_id"] == "job-owner"
    assert [
        event["principal"]
        for event in state.job_index.events_for_peer("local-feat")["events"]
    ] == ["__public_jobs__", "alice@1"]


def test_public_jobs_fall_back_to_manager_cache_when_service_returns_html(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.job_index.upsert("__public_jobs__", [{
        "job_id": "cached-public",
        "port": 8141,
        "updated_at": "2026-08-06T00:00:00Z",
        "status": "succeeded",
    }])
    monkeypatch.setattr(state, "preferred_service_port", lambda: 8141)

    def stale_service(*_args):
        raise ValueError("service returned an HTML login page")

    monkeypatch.setattr(state, "service_json", stale_service)
    with _running_manager(state) as base_url:
        with urlopen(f"{base_url}/api/jobs?scope=server&limit=20") as response:
            payload = json.loads(response.read())

    assert payload["success"] is True
    assert payload["scope"] == "server"
    assert payload["stale"] is True
    assert payload["jobs"] == [{
        "job_id": "cached-public",
        "port": 8141,
        "updated_at": "2026-08-06T00:00:00Z",
        "status": "succeeded",
    }]


def test_anonymous_server_jobs_are_bounded_to_twenty(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    calls = []

    def aggregate_public_jobs(*, cursor, limit):
        calls.append((cursor, limit))
        return {
            "public": True,
            "jobs": [],
            "page": 1,
            "total": 0,
            "total_pages": 1,
            "has_more": False,
            "next_cursor": None,
        }

    monkeypatch.setattr(state, "aggregate_public_jobs", aggregate_public_jobs)
    with _running_manager(state) as base_url:
        with urlopen(f"{base_url}/api/jobs?scope=server&limit=100") as response:
            payload = json.loads(response.read())

    assert payload["success"] is True
    assert payload["scope"] == "server"
    assert calls == [("", 20)]


def test_super_admin_server_jobs_use_permissioned_projection(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    calls = []
    monkeypatch.setattr(
        state,
        "session",
        lambda token: {
            "username": "admin@1",
            "role": "super_admin",
            "capabilities": {"manager": True, "research": True},
        } if token == "admin-token" else None,
    )

    def aggregate_server_jobs(*, principal, cursor, limit):
        calls.append((principal, cursor, limit))
        return {
            "public": False,
            "jobs": [{"job_id": "admin-job", "port": 8176}],
            "page": 1,
            "total": 1,
            "total_pages": 1,
            "has_more": False,
            "next_cursor": None,
        }

    monkeypatch.setattr(state, "aggregate_server_jobs", aggregate_server_jobs)
    monkeypatch.setattr(
        state,
        "aggregate_public_jobs",
        lambda **_: pytest.fail("super admin must not use public projection"),
    )
    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/api/jobs?scope=server&limit=100",
            headers={"Authorization": "Bearer admin-token"},
        )
        with urlopen(request) as response:
            payload = json.loads(response.read())

    assert payload["public"] is False
    assert payload["jobs"][0]["job_id"] == "admin-job"
    assert calls == [("admin@1", "", 100)]


def test_manager_job_scope_proxy_uses_one_preferred_service(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    calls = []
    monkeypatch.setattr(state, "preferred_service_port", lambda: 8141)

    def service_json(port, path, principal):
        calls.append((port, path, principal))
        return {
            "success": True,
            "scope": "server",
            "jobs": [{"job_id": "job-server", "port": 8176}],
            "page": 1,
            "page_size": 20,
            "total": 21,
            "total_pages": 2,
            "has_more": True,
            "next_cursor": "next",
        }

    monkeypatch.setattr(state, "service_json", service_json)
    with _running_manager(state) as base_url:
        with urlopen(f"{base_url}/api/jobs?scope=server&limit=20") as response:
            payload = json.loads(response.read())

    assert payload["total_pages"] == 1
    assert payload["total"] == 1
    assert payload["has_more"] is False
    assert payload["next_cursor"] is None
    assert payload["jobs"][0]["job_id"] == "job-server"
    assert calls == [(
        8141,
        "/api/jobs?scope=server&limit=20",
        "__public_jobs__",
    )]


def test_manager_account_jobs_use_one_shared_service_projection(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state._sessions[state._token_hash("user-token")] = (
        "user@1", "user", float("inf"),
    )
    calls = []
    monkeypatch.setattr(state, "preferred_service_port", lambda: 8141)
    monkeypatch.setattr(state, "service_ports", lambda: [8141, 8176])
    monkeypatch.setattr(
        state,
        "service_json",
        lambda port, path, principal: (
            calls.append((port, path, principal))
            or {
                "success": True,
                "scope": "mine",
                "jobs": [
                    {"job_id": "job-8141", "port": 8141, "updated_at": "2026-08-06T00:01:00Z"},
                    {"job_id": "job-8176", "port": 8176, "updated_at": "2026-08-06T00:02:00Z"},
                ],
                "page": 1,
                "page_size": 2,
                "total": 2,
                "total_pages": 1,
                "has_more": False,
                "next_cursor": None,
            }
        ),
    )

    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/api/jobs?scope=mine&limit=20&page=1",
            headers={"Authorization": "Bearer user-token"},
        )
        with urlopen(request) as response:
            payload = json.loads(response.read())

    assert payload["success"] is True
    assert payload["scope"] == "mine"
    assert payload["total"] == 2
    assert [job["job_id"] for job in payload["jobs"]] == [
        "job-8176", "job-8141",
    ]
    assert [job["port"] for job in payload["jobs"]] == [8176, 8141]
    assert calls == [(
        8141, "/api/jobs?scope=mine&limit=20&page=1", "user@1",
    )]


def test_public_research_attachment_route_accepts_hash_and_encoded_ref(
    tmp_path,
):
    raw = b"published source"
    digest = hashlib.sha256(raw).hexdigest()
    reference = f"attachment:sha256:{digest}"
    library = PublicResearchLibrary(tmp_path / "public-research")
    projection = {
        "schema_version": 2, "report_id": "report-attachment-route",
        "title": "Report", "language": "zh-Hans", "generation": 1,
        "components": [], "bindings": [], "assets": [],
        "local_resources": [], "related_objects": [],
        "attachments": [{
            "attachment_ref": reference, "attachment_kind": "factor_source",
            "filename": "Example.py", "media_type": "text/plain",
            "content_hash": digest,
            "content_base64": base64.b64encode(raw).decode("ascii"),
        }],
        "projection_hash": "hash",
    }
    result = library.sync({
        "report_id": "report-attachment-route", "owner_ref": "owner",
        "projection": projection,
    })
    library.configure(
        owner_ref="owner", report_id="report-attachment-route", projection=None,
        visibility="public", auto_sync=True, relay_local_files=False,
        authorized_users=[],
    )
    state = manager.ManagerState(
        tmp_path, "python", data_root=tmp_path,
        session_db_path=tmp_path / "manager.sqlite",
    )
    with _running_research_data_plane(state), _running_manager(state) as base_url:
        for suffix in (
            digest,
            "attachment%3Asha256%3A" + digest,
        ):
            with urlopen(Request(
                f"{base_url}/api/public-research/{result['publication_id']}"
                f"/attachments/{suffix}"
            )) as response:
                assert response.read() == raw


def test_public_research_visibility_marks_only_the_owner_for_local_mapping(tmp_path):
    library = PublicResearchLibrary(tmp_path / "public-research")
    projection = {
        "schema_version": 2, "report_id": "report-owner-fact",
        "title": "Owner fact", "language": "zh-Hans", "generation": 1,
        "components": [], "bindings": [], "assets": [],
        "local_resources": [], "related_objects": [], "attachments": [],
        "projection_hash": "hash-owner-fact",
    }
    library.sync({
        "report_id": projection["report_id"], "owner_ref": "owner",
        "profile_ref": "maxa", "projection": projection,
    })
    library.configure(
        owner_ref="owner", report_id=projection["report_id"], projection=None,
        visibility="public", auto_sync=True, relay_local_files=False,
        authorized_users=[],
    )

    owner_rows = library.list_visible("owner")
    other_rows = library.list_visible("other")
    assert owner_rows[0]["is_owned"] is True
    assert other_rows[0]["is_owned"] is False


def test_public_research_local_resource_route_requires_no_login_for_public_report(
    tmp_path,
):
    raw = b"downloadable local evidence"
    digest = hashlib.sha256(raw).hexdigest()
    resource_id = "b" * 24
    library = PublicResearchLibrary(tmp_path / "public-research")
    projection = {
        "schema_version": 2, "report_id": "report-local-route",
        "title": "Report", "language": "zh-Hans", "generation": 1,
        "components": [], "bindings": [], "assets": [],
        "local_resources": [{
            "resource_id": resource_id, "title": "本地证据", "filename": "evidence.txt",
            "media_type": "text/plain", "available": True, "content_hash": digest,
            "content_base64": base64.b64encode(raw).decode("ascii"),
        }],
        "related_objects": [], "attachments": [], "projection_hash": "hash",
    }
    result = library.sync({
        "report_id": "report-local-route", "owner_ref": "owner", "projection": projection,
    })
    library.configure(
        owner_ref="owner", report_id="report-local-route", projection=None,
        visibility="public", auto_sync=True, relay_local_files=False, authorized_users=[],
    )
    state = manager.ManagerState(
        tmp_path, "python", data_root=tmp_path,
        session_db_path=tmp_path / "manager.sqlite",
    )
    with _running_research_data_plane(state), _running_manager(state) as base_url:
        with urlopen(
            f"{base_url}/api/public-research/{result['publication_id']}"
            f"/local-resources/{resource_id}"
        ) as response:
            assert response.read() == raw
            assert "attachment" in response.headers["Content-Disposition"]


def test_local_research_resource_route_is_owner_scoped_and_preserves_filename(
    tmp_path, monkeypatch,
):
    state = manager.ManagerState(
        tmp_path, "python", data_root=tmp_path,
        session_db_path=tmp_path / "manager.sqlite",
    )
    monkeypatch.setattr(
        manager, "_authenticate_user", lambda _username, _password: ("owner@1", "user"),
    )
    token, _, _ = state.login("owner", "secret")
    resource_id = "c" * 24
    monkeypatch.setattr(
        state.client_state,
        "local_research_resource",
        lambda principal, local_ref, requested_id: (
            (b"private local resource", "text/plain", "notes.txt")
            if (principal, local_ref, requested_id) == ("owner@1", "record:branch", resource_id)
            else (_ for _ in ()).throw(ValueError("not found"))
        ),
    )
    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/api/client/research/record%3Abranch/local-resources/{resource_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urlopen(request) as response:
            assert response.read() == b"private local resource"
            assert response.headers["Content-Type"] == "text/plain"
            assert response.headers["Content-Disposition"] == 'attachment; filename="notes.txt"'


def test_local_research_asset_route_is_owner_scoped_and_inline(
    tmp_path, monkeypatch,
):
    state = manager.ManagerState(
        tmp_path, "python", session_db_path=tmp_path / "manager.sqlite",
    )
    monkeypatch.setattr(
        manager, "_authenticate_user", lambda _username, _password: ("owner@1", "user"),
    )
    token, _, _ = state.login("owner", "secret")
    asset_id = "d" * 24
    monkeypatch.setattr(
        state.client_state,
        "local_research_asset",
        lambda principal, local_ref, requested_id: (
            (b"private figure", "image/png", "figure.png")
            if (principal, local_ref, requested_id) == ("owner@1", "record:branch", asset_id)
            else (_ for _ in ()).throw(ValueError("not found"))
        ),
    )
    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/api/client/research/record%3Abranch/assets/{asset_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urlopen(request) as response:
            assert response.read() == b"private figure"
            assert response.headers["Content-Type"] == "image/png"
            assert response.headers["Content-Disposition"] == 'inline; filename="figure.png"'


def test_public_research_index_and_chapter_routes_are_bounded(tmp_path):
    library = PublicResearchLibrary(tmp_path / "public-research")
    projection = {
        "schema_version": 2, "report_id": "report-chapter-route",
        "title": "章节路由", "language": "zh-Hans", "generation": 2,
        "components": [
            {"component_id": "chapter-a", "parent_id": None, "kind": "chapter",
             "title": "第一章", "body": "", "content": None},
            {"component_id": "entry-a", "parent_id": "chapter-a", "kind": "entry",
             "title": "内容", "body": "正文", "content": None},
            {"component_id": "chapter-b", "parent_id": None, "kind": "chapter",
             "title": "第二章", "body": "", "content": None},
        ],
        "bindings": [], "assets": [], "local_resources": [],
        "related_objects": [], "attachments": [], "projection_hash": "hash",
    }
    result = library.sync({
        "report_id": "report-chapter-route", "owner_ref": "owner",
        "projection": projection,
    })
    library.configure(
        owner_ref="owner", report_id="report-chapter-route", projection=None,
        visibility="public", auto_sync=True, relay_local_files=False,
        authorized_users=[],
    )
    state = manager.ManagerState(tmp_path, "python", data_root=tmp_path)
    with _running_manager(state) as base_url:
        with urlopen(f"{base_url}/api/public-research/{result['publication_id']}/index") as response:
            index = json.loads(response.read())
        with urlopen(
            f"{base_url}/api/public-research/{result['publication_id']}/chapters/chapter-a"
        ) as response:
            chapter = json.loads(response.read())
        with urlopen(
            f"{base_url}/api/public-research/{result['publication_id']}"
            "/chapters/chapter-a?metadata=1"
        ) as response:
            metadata = json.loads(response.read())
        with urlopen(
            f"{base_url}/api/public-research/{result['publication_id']}"
            "/chapters/chapter-a/components/entry-a"
        ) as response:
            component = json.loads(response.read())

    assert [item["component_id"] for item in index["chapters"]] == ["chapter-a", "chapter-b"]
    assert [item["component_id"] for item in chapter["components"]] == ["chapter-a", "entry-a"]
    assert metadata["content_lazy"] is True
    assert metadata["components"][1]["body"] == ""
    assert component["components"][0]["body"] == "正文"


def test_public_research_publish_and_revoke_routes_are_loopback_only(tmp_path):
    state = manager.ManagerState(
        tmp_path,
        "python",
        data_root=tmp_path,
        session_db_path=tmp_path / "manager.sqlite",
    )
    projection = {
        "schema_version": 2,
        "report_id": "report-public-route",
        "title": "公开研究",
        "language": "zh-Hans",
        "generation": 3,
        "components": [],
        "bindings": [],
        "assets": [],
        "local_resources": [],
        "related_objects": [],
        "attachments": [],
        "projection_hash": "hash-public-route",
    }
    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/api/research-publications/publish",
            data=json.dumps({
                "owner_ref": "owner",
                "report_id": projection["report_id"],
                "projection": projection,
                "public_title": "公开标题",
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            published = json.loads(response.read())
        with urlopen(f"{base_url}/api/public-research") as response:
            reports = json.loads(response.read())["reports"]
        assert reports[0]["report_id"] == projection["report_id"]
        with urlopen(
            f"{base_url}/api/public-research/{published['publication_id']}"
        ) as response:
            mirrored = json.loads(response.read())
        assert mirrored["title"] == "公开标题"
        expected_hash = hashlib.sha256(json.dumps(
            {key: value for key, value in mirrored.items()
             if key not in {"projection_hash", "access"}},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        assert mirrored["projection_hash"] == expected_hash
        revoke = Request(
            f"{base_url}/api/research-publications/revoke",
            data=json.dumps({"publication_id": published["publication_id"]}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(revoke) as response:
            assert json.loads(response.read())["status"] == "revoked"
        with urlopen(f"{base_url}/api/public-research") as response:
            assert json.loads(response.read())["reports"] == []


def test_manager_session_survives_restart_in_sqlite_without_storing_raw_token(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(
        manager, "_authenticate_user", lambda _username, _password: (
            "admin@1", "super_admin",
        ),
    )
    session_db_path = tmp_path / "manager.sqlite"
    first = manager.ManagerState(
        tmp_path, "python", session_db_path=session_db_path,
    )
    token, _, _ = first.login("admin@1", "password")

    assert not first.sessions_path.exists()
    assert first.sessions_db_path.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(first.sessions_db_path) as database:
        row = database.execute(
            "SELECT created_at, last_seen_at, expires_at FROM manager_sessions"
        ).fetchone()
    assert row is not None
    assert token.encode() not in first.sessions_db_path.read_bytes()

    restarted = manager.ManagerState(
        tmp_path, "python", session_db_path=session_db_path,
    )
    assert restarted.session(token) == {
        "username": "admin@1",
        "alias": "admin@1",
        "role": "super_admin",
        "capabilities": {"manager": True, "research": True},
    }
    with sqlite3.connect(restarted.sessions_db_path) as database:
        expires_at = database.execute(
            "SELECT expires_at FROM manager_sessions"
        ).fetchone()[0]
    assert expires_at - manager.time.time() > 29 * 24 * 60 * 60


def test_manager_does_not_import_legacy_sessions_json(tmp_path) -> None:
    state_root = tmp_path / "manager-state"
    state_root.mkdir()
    legacy_path = state_root / "sessions.json"
    legacy_path.write_text(
        json.dumps({
            "schema_version": 2,
            "sessions": {
                "a" * 64: {
                    "principal": "GTHT@legacy@1",
                    "role": "user",
                    "expires_at": manager.time.time() + 3600,
                },
            },
        }),
        encoding="utf-8",
    )

    state = manager.ManagerState(
        tmp_path, "python", state_root=state_root,
        session_db_path=tmp_path / "manager.sqlite",
    )

    assert state._sessions == {}
    assert legacy_path.exists()


def test_active_manager_session_renews_its_idle_expiry(
    tmp_path, monkeypatch,
) -> None:
    now = 1_800_000_000.0
    monkeypatch.setattr(manager.time, "time", lambda: now)
    monkeypatch.setattr(
        manager, "_authenticate_user", lambda _username, _password: (
            "admin@1", "super_admin",
        ),
    )
    state = manager.ManagerState(
        tmp_path, "python", session_db_path=tmp_path / "manager.sqlite",
    )
    token, _, _ = state.login("admin@1", "password")
    original_expiry = next(iter(state._sessions.values()))[2]

    now += (
        manager.MANAGER_SESSION_TTL_SECONDS
        - manager.MANAGER_SESSION_REFRESH_WINDOW_SECONDS
        + 1
    )
    assert state.session(token) is not None
    renewed_expiry = next(iter(state._sessions.values()))[2]

    assert renewed_expiry > original_expiry
    assert renewed_expiry == now + manager.MANAGER_SESSION_TTL_SECONDS


def test_manager_serves_content_addressed_release_assets_directly(
    tmp_path,
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    body = b"verified-release-asset"
    digest = hashlib.sha256(body).hexdigest()
    asset = state.release_root / "assets/beta" / f"{digest}.delta"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(body)

    with _running_manager(state) as base_url:
        with urlopen(
            f"{base_url}/api/client/releases/assets/beta/{digest}.delta"
        ) as response:
            received = response.read()

    assert received == body
    assert response.headers["ETag"] == f'"{digest}"'


def test_removed_legacy_manager_page_returns_not_found(
    tmp_path, monkeypatch
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("test-capability", encoding="ascii")
    monkeypatch.setattr(
        manager.Handler,
        "_is_loopback_client",
        lambda _self: False,
    )

    with _running_manager(state) as base_url:
        with urlopen(f"{base_url}/") as response:
            assert response.status == 200
        with pytest.raises(HTTPError) as denied:
            urlopen(f"{base_url}/manager-legacy")

    assert denied.value.code == 404


def test_remote_ui_login_requires_https(tmp_path, monkeypatch) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("test-capability", encoding="ascii")
    monkeypatch.setattr(
        manager.Handler,
        "_client_ip",
        lambda _self: manager.ipaddress.ip_address("8.8.8.8"),
    )

    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/auth/login",
            data=b'{"username":"root","password":"secret"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as denied:
            urlopen(request)

    assert denied.value.code == 400
    assert "requires HTTPS" in denied.value.read().decode()


def test_public_manager_redirects_to_minimal_login_page_without_registration(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_REQUIRE_LOGIN_FOR_UI", "1")
    monkeypatch.setenv("FACTORTESTER_ALLOW_PUBLIC_REGISTRATION", "0")
    state = manager.ManagerState(tmp_path, "python")
    monkeypatch.setattr(state, "worktrees", lambda: [])

    with _running_manager(state) as base_url:
        with urlopen(f"{base_url}/jobs?scope=mine") as response:
            body = response.read().decode("utf-8")
            assert response.status == 200
            assert response.geturl().startswith(f"{base_url}/login?")
        assert "登录 FactorTester" in body
        assert "合规" in body
        assert 'id="register-form"' not in body
        assert "app-shell" not in body

        with pytest.raises(HTTPError) as api_denied:
            urlopen(f"{base_url}/api/jobs?scope=server")
        assert api_denied.value.code == 401

        register = Request(
            f"{base_url}/auth/register",
            data=b'{"username":"new-user","password":"secret"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as registration_denied:
            urlopen(register)
        assert registration_denied.value.code == 403
        assert "合规" in registration_denied.value.read().decode()


def test_public_manager_login_returns_the_authenticated_shell(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_REQUIRE_LOGIN_FOR_UI", "1")
    monkeypatch.setenv("FACTORTESTER_ALLOW_PUBLIC_REGISTRATION", "0")
    state = manager.ManagerState(tmp_path, "python")
    monkeypatch.setattr(state, "worktrees", lambda: [])
    monkeypatch.setattr(
        manager,
        "_authenticate_user",
        lambda username, password: (
            ("user@1", "user")
            if (username, password) == ("user", "secret")
            else (_ for _ in ()).throw(PermissionError("invalid"))
        ),
    )

    with _running_manager(state) as base_url:
        login = Request(
            f"{base_url}/auth/login",
            data=b'{"username":"user","password":"secret"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(login) as response:
            token = json.loads(response.read())["token"]
        shell = Request(
            f"{base_url}/jobs",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urlopen(shell) as response:
            assert response.status == 200
            assert b"<title>FTClient</title>" in response.read()


def test_public_unregistered_device_goes_directly_to_compliance_page(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_REQUIRE_LOGIN_FOR_UI", "1")
    monkeypatch.setenv("FACTORTESTER_REQUIRE_DEVICE_AUTH", "1")
    monkeypatch.setenv("FACTORTESTER_ALLOW_PUBLIC_REGISTRATION", "0")
    state = manager.ManagerState(tmp_path, "python")
    monkeypatch.setattr(state, "worktrees", lambda: [])
    monkeypatch.setattr(
        manager.Handler,
        "_client_ip",
        lambda _self: manager.ipaddress.ip_address("8.8.8.8"),
    )

    with _running_manager(state) as base_url:
        with urlopen(f"{base_url}/jobs") as response:
            body = response.read().decode("utf-8")
            assert response.geturl().startswith(f"{base_url}/compliance?")
        assert manager.PUBLIC_DEVICE_COMPLIANCE_NOTICE in body
        assert "用户与设备数量" in body
        assert "login-form" not in body
        assert "register-form" not in body
        assert "app-shell" not in body

        with urlopen(f"{base_url}/api/device/summary") as response:
            summary = json.loads(response.read())
        assert summary["public_device_count"] == 0
        assert summary["public_device_total_count"] == 0
        assert summary["public_user_count"] == 0
        assert "白名单用户" in manager.PUBLIC_DEVICE_COMPLIANCE_NOTICE

        with urlopen(f"{base_url}/login?next=/jobs") as response:
            login_body = response.read().decode("utf-8")
        assert manager.PUBLIC_DEVICE_COMPLIANCE_NOTICE in login_body
        assert "login-form" not in login_body

        english = Request(
            f"{base_url}/compliance",
            headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        with urlopen(english) as response:
            english_body = response.read().decode("utf-8")
        assert '<html lang="zh-Hans">' in english_body
        assert manager.PUBLIC_DEVICE_COMPLIANCE_NOTICE in english_body


def _visitor_request_headers(host: str, *, cookie: str = "") -> dict[str, str]:
    headers = {
        "Host": host,
        "X-Forwarded-Proto": "https",
        "X-Forwarded-For": "8.8.8.8",
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def test_ngrok_root_redirects_to_ip_compliance_with_visitor_grant(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_REQUIRE_LOGIN_FOR_UI", "1")
    monkeypatch.setenv("FACTORTESTER_REQUIRE_DEVICE_AUTH", "1")
    monkeypatch.setenv("FACTORTESTER_PUBLIC_SERVER", "1")
    monkeypatch.setenv(
        "FACTORTESTER_MANAGER_PUBLIC_ENDPOINT",
        "https://101.133.144.27:7998",
    )
    monkeypatch.setenv(
        "FACTORTESTER_PUBLIC_VISITOR_ORIGINS",
        "https://eloquence-drizzly-fencing.ngrok-free.dev",
    )
    state = manager.ManagerState(tmp_path, "python", server_id="public-main")

    opener = build_opener(_NoRedirect())
    with _running_manager(state) as base_url:
        ingress = Request(
            f"{base_url}/",
            headers=_visitor_request_headers(
                "eloquence-drizzly-fencing.ngrok-free.dev",
            ),
        )
        with pytest.raises(HTTPError) as redirected:
            opener.open(ingress)
        assert redirected.value.code == 303
        location = redirected.value.headers["Location"]
        assert location.startswith(
            "https://101.133.144.27:7998/compliance?"
        )
        query = parse_qs(urlparse(location).query)
        grant = query["grant"][0]
        assert "eloquence-drizzly-fencing.ngrok-free.dev" not in location

        target = Request(
            f"{base_url}/compliance?grant={grant}&next=%2F",
            headers=_visitor_request_headers("101.133.144.27:7998"),
        )
        with urlopen(target) as response:
            target_body = response.read().decode("utf-8")

        direct_ip = Request(
            f"{base_url}/compliance",
            headers=_visitor_request_headers("101.133.144.27:7998"),
        )
        with urlopen(direct_ip) as response:
            direct_body = response.read().decode("utf-8")

        visitor = Request(
            f"{base_url}/visitor?grant={grant}&next=%2F",
            headers=_visitor_request_headers("101.133.144.27:7998"),
        )
        with pytest.raises(HTTPError) as redeemed:
            opener.open(visitor)
        assert redeemed.value.code == 303
        visitor_cookie = redeemed.value.headers["Set-Cookie"].split(";", 1)[0]

        consumed = Request(
            f"{base_url}/compliance?grant={grant}",
            headers=_visitor_request_headers("101.133.144.27:7998"),
        )
        with urlopen(consumed) as response:
            consumed_body = response.read().decode("utf-8")

        visitor_login = Request(
            f"{base_url}/login?next=/jobs",
            headers=_visitor_request_headers(
                "101.133.144.27:7998",
                cookie=visitor_cookie,
            ),
        )
        with urlopen(visitor_login) as response:
            visitor_login_body = response.read().decode("utf-8")

    assert 'class="visitor-entry"' in target_body
    assert f"grant={grant}" in target_body
    assert 'class="visitor-entry"' not in direct_body
    assert 'class="visitor-entry"' not in consumed_body
    assert 'class="visitor-entry"' not in visitor_login_body


def test_public_session_without_current_origin_device_key_redirects_via_ingress(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_REQUIRE_LOGIN_FOR_UI", "1")
    monkeypatch.setenv("FACTORTESTER_REQUIRE_DEVICE_AUTH", "1")
    monkeypatch.setenv("FACTORTESTER_PUBLIC_SERVER", "1")
    monkeypatch.setenv(
        "FACTORTESTER_MANAGER_PUBLIC_ENDPOINT",
        "https://101.133.144.27:7998",
    )
    monkeypatch.setenv(
        "FACTORTESTER_PUBLIC_VISITOR_ORIGINS",
        "https://eloquence-drizzly-fencing.ngrok-free.dev",
    )
    state = manager.ManagerState(tmp_path, "python", server_id="public-main")
    session_token, _, _ = state._issue_session("alice@default", "user")

    opener = build_opener(_NoRedirect())
    with _running_manager(state) as base_url:
        ingress = Request(
            f"{base_url}/jobs",
            headers=_visitor_request_headers(
                "eloquence-drizzly-fencing.ngrok-free.dev",
                cookie=f"ft-manager-session={session_token}",
            ),
        )
        with pytest.raises(HTTPError) as ingress_redirect:
            opener.open(ingress)
        assert ingress_redirect.value.code == 303
        ingress_location = ingress_redirect.value.headers["Location"]
        assert ingress_location.startswith(
            "https://101.133.144.27:7998/compliance?"
        )
        ingress_query = parse_qs(urlparse(ingress_location).query)
        grant = ingress_query["grant"][0]
        ingress_compliance = Request(
            f"{base_url}/compliance?grant={grant}&next=%2Fjobs",
            headers=_visitor_request_headers("101.133.144.27:7998"),
        )
        with urlopen(ingress_compliance) as response:
            ingress_body = response.read().decode("utf-8")

        direct_ip = Request(
            f"{base_url}/jobs",
            headers=_visitor_request_headers(
                "101.133.144.27:7998",
                cookie=f"ft-manager-session={session_token}",
            ),
        )
        with pytest.raises(HTTPError) as direct_redirect:
            opener.open(direct_ip)
        assert direct_redirect.value.code == 303
        direct_location = direct_redirect.value.headers["Location"]
        assert direct_location.startswith("/compliance?next=/jobs")
        direct_compliance = Request(
            f"{base_url}{direct_location}",
            headers=_visitor_request_headers("101.133.144.27:7998"),
        )
        with urlopen(direct_compliance) as response:
            direct_body = response.read().decode("utf-8")
            assert response.geturl().startswith(f"{base_url}/compliance?")

    assert 'class="visitor-entry"' in ingress_body
    assert 'class="visitor-entry"' not in direct_body
    assert "login-form" not in ingress_body
    assert "app-shell" not in direct_body


def test_visitor_entry_redirects_to_ip_and_limits_anonymous_capabilities(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_REQUIRE_LOGIN_FOR_UI", "1")
    monkeypatch.setenv("FACTORTESTER_REQUIRE_DEVICE_AUTH", "1")
    monkeypatch.setenv("FACTORTESTER_PUBLIC_SERVER", "1")
    monkeypatch.setenv(
        "FACTORTESTER_MANAGER_PUBLIC_ENDPOINT",
        "https://101.133.144.27:7998",
    )
    monkeypatch.setenv(
        "FACTORTESTER_PUBLIC_VISITOR_ORIGINS",
        "https://eloquence-drizzly-fencing.ngrok-free.dev",
    )
    state = manager.ManagerState(tmp_path, "python", server_id="public-main")
    calls = []

    def aggregate_public_jobs(*, cursor, limit):
        calls.append((cursor, limit))
        return {
            "public": True,
            "jobs": [{"job_id": "job-1"}, {"job_id": "job-2"}],
            "page": 1,
            "total": 99,
            "total_pages": 5,
            "has_more": True,
            "next_cursor": "beyond-20",
        }

    monkeypatch.setattr(state, "aggregate_public_jobs", aggregate_public_jobs)
    opener = build_opener(_NoRedirect())
    ingress_headers = _visitor_request_headers(
        "eloquence-drizzly-fencing.ngrok-free.dev",
    )

    with _running_manager(state) as base_url:
        with pytest.raises(HTTPError) as issued:
            opener.open(Request(
                f"{base_url}/visitor?next=/jobs",
                headers=ingress_headers,
            ))
        assert issued.value.code == 303
        issued_location = issued.value.headers["Location"]
        assert issued_location.startswith(
            "https://101.133.144.27:7998/visitor?"
        )
        assert "eloquence-drizzly-fencing.ngrok-free.dev" not in issued_location
        target_query = parse_qs(urlparse(issued_location).query)
        grant = target_query["grant"][0]

        with pytest.raises(HTTPError) as redeemed:
            opener.open(Request(
                f"{base_url}/visitor?grant={grant}&next=%2Fjobs",
                headers=_visitor_request_headers("101.133.144.27:7998"),
            ))
        assert redeemed.value.code == 303
        assert redeemed.value.headers["Location"] == "/jobs"
        cookie = redeemed.value.headers["Set-Cookie"].split(";", 1)[0]
        assert cookie.startswith("ft-manager-visitor=")

        shell = Request(
            f"{base_url}/",
            headers=_visitor_request_headers(
                "101.133.144.27:7998", cookie=cookie,
            ),
        )
        with urlopen(shell) as response:
            assert response.status == 200
            assert b"<title>FTClient</title>" in response.read()

        jobs = Request(
            f"{base_url}/api/jobs?scope=server&limit=100",
            headers=_visitor_request_headers(
                "101.133.144.27:7998", cookie=cookie,
            ),
        )
        with urlopen(jobs) as response:
            payload = json.loads(response.read())
        assert payload["success"] is True
        assert [item["job_id"] for item in payload["jobs"]] == [
            "job-1", "job-2",
        ]
        assert payload["total"] == 2
        assert payload["total_pages"] == 1
        assert payload["has_more"] is False
        assert payload["next_cursor"] is None
        assert calls == [("", 20)]

        artifact_access = Request(
            f"{base_url}/api/jobs/example/artifacts/result.json/access",
            headers=_visitor_request_headers(
                "101.133.144.27:7998", cookie=cookie,
            ),
            method="POST",
        )
        with pytest.raises(HTTPError) as artifact_denied:
            urlopen(artifact_access)
        assert artifact_denied.value.code == 403
        assert "访客模式不能下载生成物" in artifact_denied.value.read().decode()

        login = Request(
            f"{base_url}/auth/login",
            data=b'{"username":"alice","password":"secret"}',
            headers={
                **_visitor_request_headers("101.133.144.27:7998", cookie=cookie),
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with pytest.raises(HTTPError) as login_denied:
            urlopen(login)
        login_payload = json.loads(login_denied.value.read())
        assert login_denied.value.code == 403
        assert login_payload["code"] == "visitor_login_forbidden"
        assert login_payload["redirect"] == "/compliance?next=/"

        login_page = Request(
            f"{base_url}/login?next=/jobs",
            headers=_visitor_request_headers(
                "101.133.144.27:7998", cookie=cookie,
            ),
        )
        with urlopen(login_page) as response:
            login_body = response.read().decode("utf-8")
        assert 'class="visitor-entry"' not in login_body
        assert 'href="/visitor?next=/' not in login_body

        with pytest.raises(HTTPError) as manual:
            opener.open(Request(
                f"{base_url}/visitor?visitor=1",
                headers=_visitor_request_headers("101.133.144.27:7998"),
            ))
        assert manual.value.code == 303
        assert manual.value.headers["Location"].startswith("/compliance?")


def test_public_compliance_page_bootstraps_device_login_with_visible_status() -> None:
    from server.manager.http.pages import compliance_page

    body = compliance_page("/jobs").decode("utf-8")

    assert 'id="device-auth-status"' in body
    assert 'role="status"' in body
    assert "正在检查本浏览器的设备凭证" in body
    assert "检测到已登记设备，正在自动登录" in body
    assert "当前浏览器来源没有已登记的设备密钥" in body
    assert "设备自动登录失败" in body
    assert 'text.split("{"+key+"}").join(String(value))' in body
    assert 'text.split("{{"+key+"}}")' not in body
    assert 'window.addEventListener("online",authenticate)' in body
    assert 'document.addEventListener("visibilitychange"' in body
    assert "MAX_AUTHENTICATION_RUNS" in body
    assert "scheduleAuthenticationRetry" in body
    assert "transientFailure" in body
    assert 'authenticate().finally(loadCount)' in body
    assert 'window.addEventListener("load",startAuthentication' in body
    assert "设备连接暂时失败，正在自动重试" in body
    assert "签名阶段失败" in body
    assert 'redirect:"error"' in body
    assert 'mode:"same-origin"' in body
    assert "challengeNetworkFailed" in body
    assert "verifyNetworkFailed" in body
    assert "window.isSecureContext===false" in body

def test_public_device_auth_auto_logs_bound_user_and_blocks_account_switch(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_REQUIRE_LOGIN_FOR_UI", "1")
    monkeypatch.setenv("FACTORTESTER_REQUIRE_DEVICE_AUTH", "1")
    monkeypatch.setenv("FACTORTESTER_ALLOW_PUBLIC_REGISTRATION", "0")
    state = manager.ManagerState(tmp_path, "python", server_id="public-main")
    monkeypatch.setattr(manager.Handler, "_has_secure_ui_transport", lambda _self: True)
    monkeypatch.setattr(manager.Handler, "_is_loopback_client", lambda _self: False)
    monkeypatch.setattr(
        state,
        "login",
        lambda *_values: pytest.fail(
            "password login must not run on a device-gated public Manager"
        ),
    )
    monkeypatch.setattr(
        state.device_registry,
        "verify",
        lambda **_values: {
            "device_id": "device-bound-to-alice",
            "username": "alice@default",
        },
    )
    bound_users = []

    def login_device(username, **values):
        bound_users.append(username)
        return state._issue_session(
            username,
            "user",
            authentication="device",
            origin=str(values.get("origin") or ""),
        )

    monkeypatch.setattr(state, "login_device", login_device)

    with _running_manager(state) as base_url:
        password_login = Request(
            f"{base_url}/auth/login",
            data=b'{"username":"bob@default","password":"secret"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as denied:
            urlopen(password_login)
        assert denied.value.code == 403
        assert "device authentication required" in denied.value.read().decode()

        challenge_request = Request(
            f"{base_url}/api/device/challenge",
            data=b'{"device_id":"device-bound-to-alice"}',
            headers={
                **_visitor_request_headers("101.133.144.27:7998"),
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(challenge_request) as response:
            challenge = json.loads(response.read())
        verify_request = Request(
            f"{base_url}/api/device/verify",
            data=json.dumps({
                "challenge_id": challenge["challenge_id"],
                "device_id": "device-bound-to-alice",
                "public_key": {},
                "signature": "ignored-by-test-seam",
                "username": "bob@default",
            }).encode(),
            headers={
                **_visitor_request_headers("101.133.144.27:7998"),
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(verify_request) as response:
            authenticated = json.loads(response.read())
            session_cookie = response.headers["Set-Cookie"].split(";", 1)[0]

        home_request = Request(
            f"{base_url}/",
            headers={
                "Host": "101.133.144.27:7998",
                "Cookie": session_cookie,
            },
        )
        with urlopen(home_request) as response:
            assert response.status == 200

    assert authenticated["username"] == "alice@default"
    assert state.session(authenticated["token"]) is not None
    assert bound_users == ["alice@default"]


def test_device_session_is_bound_to_its_issuing_origin(tmp_path) -> None:
    state = manager.ManagerState(tmp_path, "python", server_id="public-main")
    device_token, _, _ = state._issue_session(
        "alice@default",
        "user",
        authentication="device",
        origin="https://101.133.144.27:7998",
    )
    password_token, _, _ = state._issue_session("alice@default", "user")

    assert state.session_allows_device_origin(
        device_token,
        "https://101.133.144.27:7998",
    )
    assert not state.session_allows_device_origin(
        device_token,
        "https://eloquence-drizzly-fencing.ngrok-free.dev",
    )
    assert not state.session_allows_device_origin(
        password_token,
        "https://101.133.144.27:7998",
    )


def test_direct_https_manager_accepts_public_ui_login_and_marks_cookie_secure(
    tmp_path, monkeypatch,
) -> None:
    manager.ManagerState(tmp_path, "python")
    handler = object.__new__(manager.Handler)
    handler.server = type("TLSServer", (), {"tls_enabled": True})()
    handler.client_address = ("8.8.8.8", 443)
    handler.headers = {}

    assert handler._has_secure_ui_transport()
    assert "Secure;" in handler._session_cookie("session-token")


def test_private_lan_ui_can_login_over_direct_http(
    tmp_path, monkeypatch
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("internal-capability", encoding="ascii")
    monkeypatch.setattr(
        manager.Handler,
        "_client_ip",
        lambda _self: manager.ipaddress.ip_address("10.98.184.25"),
    )
    monkeypatch.setattr(
        manager,
        "_authenticate_user",
        lambda username, password: (
            ("root@1", "super_admin")
            if (username, password) == ("root", "secret")
            else (_ for _ in ()).throw(PermissionError("invalid"))
        ),
    )
    monkeypatch.setattr(state, "worktrees", lambda: [])

    with _running_manager(state) as base_url:
        login = Request(
            f"{base_url}/auth/login",
            data=b'{"username":"root","password":"secret"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(login) as response:
            session = json.loads(response.read())
        request = Request(
            f"{base_url}/api/worktrees",
            headers={"Authorization": f"Bearer {session['token']}"},
        )
        with urlopen(request) as response:
            assert response.status == 200


def test_capability_token_is_created_atomically_with_owner_only_mode(
    tmp_path, monkeypatch
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    monkeypatch.setattr(Path, "chmod", lambda self, mode: None)
    previous_umask = os.umask(0)
    try:
        token = state.capability_token()
    finally:
        os.umask(previous_umask)

    assert token
    assert state.capability_path.stat().st_mode & 0o777 == 0o600


def test_worktree_api_uses_opaque_instance_id_without_absolute_path(
    tmp_path, monkeypatch
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("test-capability", encoding="ascii")
    source = tmp_path / "private" / "issue-141"
    worktree = manager.Worktree(
        path=source,
        branch="fix/issue-141-secure-manager",
        head="abcdef12",
        label="fix/issue-141-secure-manager",
        port=8141,
    )
    monkeypatch.setattr(state, "worktrees", lambda: [worktree])
    monkeypatch.setattr(manager, "port_in_use", lambda _port: False)

    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/api/worktrees",
            headers={"Authorization": "Bearer test-capability"},
        )
        with urlopen(request) as response:
            raw = response.read().decode("utf-8")

    payload = json.loads(raw)
    item = payload["worktrees"][0]
    assert item["instance_id"].startswith("worktree-")
    assert item["branch"] == "fix/issue-141-secure-manager"
    assert item["head"] == "abcdef12"
    assert "path" not in item
    assert str(source) not in raw


def test_mutation_rejects_legacy_path_and_port_payload(tmp_path, monkeypatch) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("test-capability", encoding="ascii")
    called = []
    monkeypatch.setattr(
        state,
        "restart_bundle",
        lambda path, port: called.append((path, port)) or "restarted",
    )

    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/restart-bundle",
            data=urlencode({"path": str(tmp_path), "port": "8141"}).encode(),
            headers={
                "Authorization": "Bearer test-capability",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with pytest.raises(HTTPError) as denied:
            urlopen(request)

    assert denied.value.code == 400
    assert called == []


@pytest.mark.parametrize(
    "action",
    [
        "start", "stop", "restart-api", "restart-bundle", "force-stop",
        "vibe/start", "vibe/stop",
    ],
)
def test_every_mutation_requires_bearer_capability(tmp_path, action) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("test-capability", encoding="ascii")

    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/{action}",
            data=urlencode({"instance_id": "untrusted"}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with pytest.raises(HTTPError) as denied:
            urlopen(request)

    assert denied.value.code == 401


def test_mutation_resolves_opaque_instance_id_server_side(tmp_path, monkeypatch) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("test-capability", encoding="ascii")
    source = tmp_path / "private" / "issue-141"
    worktree = manager.Worktree(
        path=source,
        branch="fix/issue-141-secure-manager",
        head="abcdef12",
        label="fix/issue-141-secure-manager",
        port=8141,
    )
    monkeypatch.setattr(state, "worktrees", lambda: [worktree])
    called = []
    monkeypatch.setattr(
        state,
        "restart_bundle",
        lambda path, port: called.append((path, port)) or "restarted",
    )
    instance_id = state.instance_id(worktree)

    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/restart-bundle",
            data=urlencode({"instance_id": instance_id}).encode(),
            headers={
                "Authorization": "Bearer test-capability",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urlopen(request) as response:
            raw = response.read().decode("utf-8")

    assert called == [(source, 8141)]
    assert json.loads(raw) == {
        "success": True,
        "instance_id": instance_id,
        "message": "restarted",
    }
    assert str(source) not in raw


def test_async_mutation_responds_before_the_destructive_action(
    tmp_path,
    monkeypatch,
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("test-capability", encoding="ascii")
    source = tmp_path / "private" / "issue-141"
    worktree = manager.Worktree(
        path=source,
        branch="fix/issue-141-secure-manager",
        head="abcdef12",
        label="fix/issue-141-secure-manager",
        port=8141,
    )
    monkeypatch.setattr(state, "worktrees", lambda: [worktree])
    called = []
    scheduled = []
    monkeypatch.setattr(
        state,
        "restart_bundle",
        lambda path, port: called.append((path, port)) or "restarted",
    )
    monkeypatch.setattr(
        state,
        "submit_action",
        lambda operation, label: scheduled.append((operation, label)),
    )
    instance_id = state.instance_id(worktree)

    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/restart-bundle",
            data=urlencode({"instance_id": instance_id}).encode(),
            headers={
                "Authorization": "Bearer test-capability",
                "Content-Type": "application/x-www-form-urlencoded",
                "Prefer": "respond-async",
            },
            method="POST",
        )
        with urlopen(request) as response:
            raw = response.read().decode("utf-8")
            assert response.status == 202

    assert json.loads(raw) == {
        "success": True,
        "submitted": True,
        "instance_id": instance_id,
    }
    assert called == []
    operation, label = scheduled[0]
    assert label == f"/restart-bundle {instance_id}"
    operation()
    assert called == [(source, 8141)]


def test_mutation_error_does_not_disclose_managed_path(tmp_path, monkeypatch) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("test-capability", encoding="ascii")
    source = tmp_path / "private" / "issue-141"
    worktree = manager.Worktree(
        path=source,
        branch="fix/issue-141-secure-manager",
        head="abcdef12",
        label="fix/issue-141-secure-manager",
        port=8141,
    )
    monkeypatch.setattr(state, "worktrees", lambda: [worktree])

    def fail(_path, _port):
        raise RuntimeError(f"failed under {source}")

    monkeypatch.setattr(state, "restart_bundle", fail)
    instance_id = state.instance_id(worktree)

    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/restart-bundle",
            data=urlencode({"instance_id": instance_id}).encode(),
            headers={
                "Authorization": "Bearer test-capability",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with pytest.raises(HTTPError) as failed:
            urlopen(request)
        raw = failed.value.read().decode("utf-8")

    assert failed.value.code == 409
    assert str(source) not in raw


def test_worktree_api_does_not_leak_filesystem_paths(
    tmp_path, monkeypatch
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("test-capability", encoding="ascii")
    source = tmp_path / "private" / "issue-141"
    worktree = manager.Worktree(
        path=source,
        branch="fix/issue-141-secure-manager",
        head="abcdef12",
        label="fix/issue-141-secure-manager",
        port=8141,
    )
    monkeypatch.setattr(state, "worktrees", lambda: [worktree])
    monkeypatch.setattr(manager, "port_in_use", lambda _port: False)

    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/api/worktrees",
            headers={"Authorization": "Bearer test-capability"},
        )
        with urlopen(request) as response:
            payload = json.loads(response.read())

    raw = json.dumps(payload)
    assert str(source) not in raw
    assert str(manager.VIBE_TRADING_ROOT) not in raw
    assert "path" not in payload["worktrees"][0]
    assert payload["worktrees"][0]["instance_id"] == state.instance_id(worktree)


def test_loopback_browser_can_submit_same_origin_action(
    tmp_path, monkeypatch
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("test-capability", encoding="ascii")
    source = tmp_path / "private" / "issue-141"
    worktree = manager.Worktree(
        path=source,
        branch="fix/issue-141-secure-manager",
        head="abcdef12",
        label="fix/issue-141-secure-manager",
        port=8141,
    )
    monkeypatch.setattr(state, "worktrees", lambda: [worktree])
    called = []
    monkeypatch.setattr(
        state,
        "start",
        lambda path, port: called.append((path, port)) or "started",
    )

    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/start",
            data=urlencode({
                "instance_id": state.instance_id(worktree),
            }).encode(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": base_url,
            },
            method="POST",
        )
        with urlopen(request) as response:
            assert response.status == 200

    assert called == [(source, 8141)]


@pytest.mark.parametrize("branch", ["main", "master"])
def test_primary_branch_uses_fixed_port_8000(tmp_path, monkeypatch, branch) -> None:
    worktree = tmp_path / "repo"
    worktree.mkdir()
    porcelain = (
        f"worktree {worktree}\n"
        "HEAD abcdef1234567890\n"
        f"branch refs/heads/{branch}\n\n"
    )
    monkeypatch.setattr(
        manager.subprocess,
        "check_output",
        lambda *args, **kwargs: porcelain,
    )

    result = manager.ManagerState(worktree, "python").worktrees()

    assert len(result) == 1
    assert result[0].branch == branch
    assert result[0].port == 8000


def test_service_load_projects_live_daemon_health() -> None:
    assert manager.ManagerState._load_from_health({
        "active_executors": 2,
        "active_planners": 1,
        "queue_depth": 4,
    }) == {
        "load": 10.0,
        "active_jobs": 3,
        "queue_depth": 4,
    }


def test_detached_manager_exposes_configured_fixed_service_instance(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(
        manager.ManagerState,
        "_worktree_entries",
        lambda self: [
            {
                "worktree": str(tmp_path),
                "HEAD": "e5707434d001991c89871f743a0583086d393c6e",
            },
        ],
    )
    monkeypatch.setattr(
        manager.ManagerState,
        "_revision_for_path",
        lambda self, path=None: "e" * 40,
    )
    state = manager.ManagerState(
        tmp_path,
        "python",
        server_role="main",
        fixed_port=8000,
        fixed_branch="main",
    )

    result = state.worktrees()

    assert [(item.branch, item.port, item.path) for item in result] == [
        ("main", 8000, tmp_path.resolve()),
    ]
    assert state.worktree_for_instance(state.instance_id(result[0])) == result[0]


def test_federation_registration_advertises_online_issue_worktree_ports(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(
        tmp_path,
        "python",
        server_role="feat",
        server_id="local-feat",
    )
    routes = [
        manager.ServiceRoute(
            server_id="local-feat", role="feat", branch="fix/issue-141-demo",
            revision="a" * 40, port=8141, online=True,
        ),
        manager.ServiceRoute(
            server_id="local-feat", role="feat", branch="fix/issue-152-demo",
            revision="b" * 40, port=8152, online=True,
        ),
        manager.ServiceRoute(
            server_id="local-feat", role="feat", branch="fix/issue-160-demo",
            revision="c" * 40, port=8160, online=False,
        ),
    ]
    monkeypatch.setattr(
        state,
        "local_service_routes",
        lambda include_offline=True: routes if include_offline else routes[:2],
    )

    payload = state.federation_registration_payload(
        "http://local.example:7998",
    )

    assert state.advertised_federation_ports() == (8141, 8152)
    assert [item["port"] for item in payload["ports"]] == [8141, 8152]
    assert "artifact_endpoint" not in payload


def test_federation_attachment_allows_automatic_port_discovery(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(tmp_path, "python", server_role="feat")
    monkeypatch.setattr(
        state,
        "local_service_routes",
        lambda include_offline=True: [],
    )
    started = []
    monkeypatch.setattr(
        state,
        "start_federation_announcer",
        lambda **kwargs: started.append(kwargs),
    )

    result = state.update_federation_config({
        "enabled": True,
        "bootstrap_url": "http://10.77.0.2:17998/api/federation/register",
        "public_endpoint": "https://local.example:7998",
        "registration_token": "registration-token",
        "ports": [],
    })

    assert result["config"]["ports"] == []
    assert started[0]["bootstrap_url"] == (
        "http://10.77.0.2:17998/api/federation/register"
    )
    assert started[0]["ports"] == ()
    assert "artifact_endpoint" not in started[0]


def test_federation_attachment_repairs_stale_wireguard_public_endpoint(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(
        tmp_path,
        "python",
        server_role="feat",
        server_id="local-feat",
    )
    state.manager_public_endpoint = "http://192.168.1.10:7998"
    started = []
    monkeypatch.setattr(
        state,
        "start_federation_announcer",
        lambda **kwargs: started.append(kwargs),
    )

    result = state.update_federation_config({
        "enabled": True,
        "bootstrap_url": "http://10.77.0.2:17998/api/federation/register",
        "public_endpoint": "http://10.77.0.3:7998",
        "registration_token": "registration-token",
        "ports": [],
    })

    assert result["config"]["public_endpoint"] == (
        "http://192.168.1.10:7998"
    )
    assert started[0]["endpoint"] == "http://192.168.1.10:7998"


def test_cleanup_detached_worktrees_removes_snapshots_and_prunes(tmp_path, monkeypatch) -> None:
    detached = tmp_path / ".workspace" / "manager-sources" / "detached"
    detached.mkdir(parents=True)
    porcelain = (
        f"worktree {tmp_path}\n"
        "HEAD e5707434d001991c89871f743a0583086d393c6e\n"
        "branch refs/heads/main\n\n"
        f"worktree {detached}\n"
        "HEAD 689e141e78c90d5cbb6d7b96e236919056db7525\n"
        "detached\n\n"
    )
    commands = []
    monkeypatch.setattr(
        manager.subprocess,
        "check_output",
        lambda *args, **kwargs: porcelain,
    )
    monkeypatch.setattr(
        manager.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command),
    )
    state = manager.ManagerState(tmp_path, "python")

    removed = state.cleanup_detached_worktrees()

    assert removed == [detached.resolve()]
    assert commands[0][:4] == ["git", "worktree", "remove", "--force"]
    assert commands[1] == ["git", "worktree", "prune", "--expire", "now"]


def test_cleanup_detached_worktrees_skips_bare_repository_marker(tmp_path, monkeypatch) -> None:
    detached = tmp_path / ".workspace" / "manager-sources" / "detached"
    detached.mkdir(parents=True)
    bare = tmp_path / "repo.git"
    porcelain = (
        f"worktree {tmp_path}\n"
        "HEAD e5707434d001991c89871f743a0583086d393c6e\n"
        "branch refs/heads/main\n\n"
        f"worktree {bare}\n"
        "bare\n\n"
        f"worktree {detached}\n"
        "HEAD 689e141e78c90d5cbb6d7b96e236919056db7525\n"
        "detached\n\n"
    )
    commands = []
    monkeypatch.setattr(
        manager.subprocess,
        "check_output",
        lambda *args, **kwargs: porcelain,
    )
    monkeypatch.setattr(
        manager.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command),
    )
    state = manager.ManagerState(tmp_path, "python")

    assert state.cleanup_detached_worktrees() == [detached.resolve()]
    assert commands[0][-1] == str(detached.resolve())
    assert commands[1] == ["git", "worktree", "prune", "--expire", "now"]


def test_cleanup_detached_worktrees_leaves_missing_paths_to_prune(tmp_path, monkeypatch) -> None:
    missing = tmp_path / ".workspace" / "manager-sources" / "missing-detached"
    porcelain = (
        f"worktree {tmp_path}\n"
        "HEAD e5707434d001991c89871f743a0583086d393c6e\n"
        "branch refs/heads/main\n\n"
        f"worktree {missing}\n"
        "HEAD 689e141e78c90d5cbb6d7b96e236919056db7525\n"
        "detached\n\n"
    )
    commands = []
    monkeypatch.setattr(
        manager.subprocess,
        "check_output",
        lambda *args, **kwargs: porcelain,
    )
    monkeypatch.setattr(
        manager.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command),
    )
    state = manager.ManagerState(tmp_path, "python")

    assert state.cleanup_detached_worktrees() == []
    assert commands == [["git", "worktree", "prune", "--expire", "now"]]


def test_cleanup_detached_worktrees_preserves_active_manager_source(
    tmp_path, monkeypatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    active_source = repository / ".workspace" / "manager-sources" / ("a" * 40)
    active_source.mkdir(parents=True)
    product_docs = active_source / "product_docs"
    product_docs.mkdir()
    (product_docs / "getting-started.md").write_text(
        "## Getting started {#getting-started}\n\nTemporary manager fixture.\n",
        encoding="utf-8",
    )
    (product_docs / "manifest.json").write_text(
        json.dumps({
            "schema_version": 1,
            "title": "Fixture docs",
            "default_page": "getting-started",
            "sections": [{
                "id": "guide",
                "title": "Guide",
                "pages": [{
                    "slug": "getting-started",
                    "title": "Getting started",
                    "summary": "Fixture",
                    "kind": "guide",
                    "source": "getting-started.md",
                }],
            }],
        }),
        encoding="utf-8",
    )
    porcelain = (
        f"worktree {repository}\n"
        "HEAD e5707434d001991c89871f743a0583086d393c6e\n"
        "branch refs/heads/main\n\n"
        f"worktree {active_source}\n"
        "HEAD 689e141e78c90d5cbb6d7b96e236919056db7525\n"
        "detached\n\n"
    )
    commands = []
    monkeypatch.setattr(manager, "_REPO_ROOT", active_source)
    monkeypatch.setattr(
        manager.subprocess,
        "check_output",
        lambda *args, **kwargs: porcelain,
    )
    monkeypatch.setattr(
        manager.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command),
    )
    state = manager.ManagerState(repository, "python")

    assert state.cleanup_detached_worktrees() == []
    assert commands == [["git", "worktree", "prune", "--expire", "now"]]


def test_cleanup_detached_worktrees_preserves_external_release(
    tmp_path, monkeypatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    release = tmp_path / "deploy" / "releases" / ("b" * 40)
    release.mkdir(parents=True)
    porcelain = (
        f"worktree {repository}\n"
        "HEAD e5707434d001991c89871f743a0583086d393c6e\n"
        "branch refs/heads/main\n\n"
        f"worktree {release}\n"
        f"HEAD {'b' * 40}\n"
        "detached\n\n"
    )
    commands = []
    monkeypatch.setattr(
        manager.subprocess,
        "check_output",
        lambda *args, **kwargs: porcelain,
    )
    monkeypatch.setattr(
        manager.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command),
    )
    state = manager.ManagerState(repository, "python")

    assert state.cleanup_detached_worktrees() == []
    assert release.exists()
    assert commands == [["git", "worktree", "prune", "--expire", "now"]]


def test_worktrees_hide_immutable_manager_source_cache(tmp_path, monkeypatch) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    manager_source = repository / ".workspace" / "manager-sources" / ("a" * 40)
    manager_source.mkdir(parents=True)
    service = repository / ".workspace" / "fix" / "issue-141-client"
    service.mkdir(parents=True)
    porcelain = (
        f"worktree {repository}\n"
        "HEAD e5707434d001991c89871f743a0583086d393c6e\n"
        "branch refs/heads/main\n\n"
        f"worktree {manager_source}\n"
        f"HEAD {'a' * 40}\n"
        "detached\n\n"
        f"worktree {service}\n"
        "HEAD 689e141e78c90d5cbb6d7b96e236919056db7525\n"
        "branch refs/heads/fix/issue-141-client\n\n"
    )
    monkeypatch.setattr(
        manager.subprocess,
        "check_output",
        lambda *args, **kwargs: porcelain,
    )

    worktrees = manager.ManagerState(repository, "python").worktrees()

    assert [item.branch for item in worktrees] == ["main", "fix/issue-141-client"]
    assert [item.port for item in worktrees] == [8000, 8141]


def test_worktrees_skip_bare_repository_entry(tmp_path, monkeypatch) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    porcelain = (
        f"worktree {repository}.git\n"
        "bare\n\n"
        f"worktree {repository}\n"
        "HEAD e5707434d001991c89871f743a0583086d393c6e\n"
        "branch refs/heads/main\n\n"
    )
    monkeypatch.setattr(
        manager.subprocess,
        "check_output",
        lambda *args, **kwargs: porcelain,
    )

    worktrees = manager.ManagerState(repository, "python").worktrees()

    assert [(item.branch, item.port) for item in worktrees] == [("main", 8000)]


def test_manager_starts_bundle_and_api_restart_preserves_daemon(tmp_path, monkeypatch) -> None:
    (tmp_path / "start_server.py").write_text("", encoding="ascii")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "research_job_daemon.py").write_text("", encoding="ascii")
    created = []

    def fake_popen(command, **kwargs):
        process = _Process(command)
        created.append((process, kwargs))
        return process

    monkeypatch.setattr(manager.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(manager.subprocess, "check_output", lambda *args, **kwargs: "abc123\n")
    monkeypatch.setattr(manager, "port_in_use", lambda port: False)
    monkeypatch.setattr(manager.ManagerState, "_terminate", staticmethod(lambda process: setattr(process, "returncode", 0)))
    state = manager.ManagerState(tmp_path, "python")

    state.start(tmp_path, 8135)
    bundle = state.processes[state.key(tmp_path)]
    daemon_pid = bundle.daemon.pid
    old_api_pid = bundle.api.pid
    state.restart_api(tmp_path, 8135)

    assert bundle.daemon.pid == daemon_pid
    assert bundle.daemon.poll() is None
    assert bundle.api.pid != old_api_pid
    assert created[0][0].command[1] == "scripts/research_job_daemon.py"
    assert created[1][1]["env"]["GTHT_DEPLOYMENT_ID"].endswith("-8135")
    assert created[1][1]["env"]["GTHT_JOB_DAEMON_SOCKET"] == str(bundle.socket_path)
    assert created[1][1]["env"]["FACTORTESTER_WERKZEUG_RELOADER"] == "0"
    assert "FLASK_SECRET_KEY" not in created[1][1]["env"]
    assert "FLASK_SECRET_KEY" not in created[2][1]["env"]
    assert "GTHT_MANAGER_CAPABILITY_TOKEN" not in created[0][1]["env"]
    assert created[1][1]["env"]["GTHT_MANAGER_CAPABILITY_TOKEN"]
    assert created[2][1]["env"]["GTHT_MANAGER_CAPABILITY_TOKEN"]


def test_manager_reclaims_services_after_control_process_restart(tmp_path, monkeypatch) -> None:
    path = tmp_path / "issue-141-service"
    path.mkdir()
    state = manager.ManagerState(tmp_path, "python")
    worktree = manager.Worktree(
        path=path,
        branch="fix/issue-141-service",
        head="abc12345",
        label="fix/issue-141-service",
        port=8141,
    )
    monkeypatch.setattr(state, "worktrees", lambda: [worktree])
    monkeypatch.setattr(manager, "port_in_use", lambda _port: True)
    monkeypatch.setattr(
        state,
        "_process_listing",
        lambda: [
            (41001, "python start_server.py --port 8141"),
            (41002, "python scripts/research_job_daemon.py "
             "--deployment-id issue-141-service-8141 "
             f"--socket {path.resolve() / '.workspace/runtime/issue-141-service-8141.sock'}"),
        ],
    )
    monkeypatch.setattr(state, "_process_cwd", lambda _pid: path.resolve())
    monkeypatch.setattr(manager.os, "kill", lambda _pid, _signal: None)

    assert state.is_running(path)
    assert state.daemon_running(path)
    bundle = state.processes[state.key(path)]
    assert bundle.api.pid == 41001
    assert bundle.daemon.pid == 41002


def test_manager_restores_desired_services_after_graceful_restart(
    tmp_path, monkeypatch,
) -> None:
    path = tmp_path / "issue-141-service"
    path.mkdir()
    (path / "start_server.py").write_text("", encoding="ascii")
    (path / "scripts").mkdir()
    (path / "scripts" / "research_job_daemon.py").write_text(
        "", encoding="ascii",
    )
    worktree = manager.Worktree(
        path=path,
        branch="fix/issue-141-service",
        head="abc12345",
        label="fix/issue-141-service",
        port=8141,
    )
    created = []

    def fake_popen(command, **kwargs):
        process = _Process(command)
        created.append((process, kwargs))
        return process

    monkeypatch.setattr(manager.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        manager.subprocess, "check_output", lambda *args, **kwargs: "abc123\n",
    )
    monkeypatch.setattr(manager, "port_in_use", lambda _port: False)
    monkeypatch.setattr(
        manager.ManagerState, "worktrees", lambda _self: [worktree],
    )
    monkeypatch.setattr(
        manager.ManagerState,
        "_terminate",
        staticmethod(lambda process: setattr(process, "returncode", 0)),
    )

    first = manager.ManagerState(
        path, "python", state_root=tmp_path / "manager-state",
    )
    first.start(path, 8141)
    first.stop_all()

    restarted = manager.ManagerState(
        path, "python", state_root=tmp_path / "manager-state",
    )
    restored = restarted.restore_desired_services()

    assert restored == [{
        "path": str(path.resolve()),
        "port": 8141,
        "status": "started",
    }]
    assert restarted.is_running(path)
    assert restarted.daemon_running(path)
    assert len(created) == 4


def test_explicit_service_stop_clears_restart_intent(tmp_path, monkeypatch) -> None:
    path = tmp_path / "issue-141-service"
    path.mkdir()
    (path / "start_server.py").write_text("", encoding="ascii")
    (path / "scripts").mkdir()
    (path / "scripts" / "research_job_daemon.py").write_text(
        "", encoding="ascii",
    )
    worktree = manager.Worktree(
        path=path,
        branch="fix/issue-141-service",
        head="abc12345",
        label="fix/issue-141-service",
        port=8141,
    )

    monkeypatch.setattr(
        manager.subprocess,
        "Popen",
        lambda command, **_kwargs: _Process(command),
    )
    monkeypatch.setattr(
        manager.subprocess, "check_output", lambda *args, **kwargs: "abc123\n",
    )
    monkeypatch.setattr(manager, "port_in_use", lambda _port: False)
    monkeypatch.setattr(
        manager.ManagerState, "worktrees", lambda _self: [worktree],
    )
    monkeypatch.setattr(
        manager.ManagerState,
        "_terminate",
        staticmethod(lambda process: setattr(process, "returncode", 0)),
    )

    state = manager.ManagerState(
        path, "python", state_root=tmp_path / "manager-state",
    )
    state.start(path, 8141)
    state.stop(path, force=True)

    restarted = manager.ManagerState(
        path, "python", state_root=tmp_path / "manager-state",
    )
    assert restarted.restore_desired_services() == []
    assert not restarted.is_running(path)


def test_service_env_adds_repo_harness_without_losing_pythonpath(
    tmp_path,
    monkeypatch,
) -> None:
    existing = os.pathsep.join(["/existing/one", "/existing/two"])
    monkeypatch.setenv("PYTHONPATH", existing)
    monkeypatch.setattr(
        manager.subprocess,
        "check_output",
        lambda *args, **kwargs: "abc123\n",
    )
    state = manager.ManagerState(tmp_path, "python")

    env, _, _ = state._service_env(tmp_path, 8000)

    harness = str((tmp_path / "tools/cli/agent-harness").resolve())
    entries = env["PYTHONPATH"].split(os.pathsep)
    assert entries == [harness, "/existing/one", "/existing/two"]
    assert entries.count(harness) == 1
    assert env["FACTORTESTER_SERVICE_HOST"] == "127.0.0.1"


def test_service_env_uses_native_daemon_runtime_directory(
    tmp_path,
    monkeypatch,
) -> None:
    runtime_dir = tmp_path / "container-run"
    monkeypatch.setenv("FACTORTESTER_JOB_DAEMON_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setattr(
        manager.subprocess,
        "check_output",
        lambda *args, **kwargs: "abc123\n",
    )
    repo = tmp_path / "repo"
    state = manager.ManagerState(repo, "python")

    env, deployment_id, socket_path = state._service_env(repo, 7999)

    assert socket_path == runtime_dir / f"{deployment_id}.sock"
    assert env["GTHT_JOB_DAEMON_SOCKET"] == str(socket_path)


def test_federation_settings_offer_only_online_service_ports(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(tmp_path, "python", server_role="feat")
    token, _, _ = state._issue_session("admin@default", "super_admin")
    routes = [
        manager.ServiceRoute(
            server_id=state.server_id,
            role="feat",
            branch="fix/issue-141-online",
            revision="a" * 40,
            port=8141,
            endpoint="http://127.0.0.1:7998",
            online=True,
        ),
        manager.ServiceRoute(
            server_id=state.server_id,
            role="feat",
            branch="fix/issue-999-offline",
            revision="b" * 40,
            port=8999,
            endpoint="http://127.0.0.1:7998",
            online=False,
        ),
    ]
    monkeypatch.setattr(
        state,
        "local_service_routes",
        lambda *, include_offline=True: (
            routes if include_offline else [route for route in routes if route.online]
        ),
    )

    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/api/federation/config",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urlopen(request) as response:
            payload = json.loads(response.read())

    assert [item["port"] for item in payload["available_ports"]] == [8141]


def test_bundle_restart_recovers_api_when_daemon_has_died(
    tmp_path,
    monkeypatch,
) -> None:
    (tmp_path / "start_server.py").write_text("", encoding="ascii")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "research_job_daemon.py").write_text(
        "", encoding="ascii"
    )
    old_api = _Process(["api"])
    dead_daemon = _Process(["daemon"])
    dead_daemon.returncode = 1
    state = manager.ManagerState(tmp_path, "python")
    state.processes[state.key(tmp_path)] = manager.ServiceBundle(
        api=old_api,
        daemon=dead_daemon,
        socket_path=tmp_path / "jobs.sock",
        deployment_id="test",
    )
    monkeypatch.setattr(manager, "port_in_use", lambda _port: False)
    monkeypatch.setattr(
        manager.subprocess,
        "check_output",
        lambda *args, **kwargs: "abc123\n",
    )
    monkeypatch.setattr(
        manager.subprocess,
        "Popen",
        lambda command, **kwargs: _Process(command),
    )
    monkeypatch.setattr(
        manager.ManagerState,
        "_terminate",
        staticmethod(lambda process: setattr(process, "returncode", 0)),
    )

    state.restart_bundle(tmp_path, 8135)

    replacement = state.processes[state.key(tmp_path)]
    assert old_api.returncode == 0
    assert replacement.api is not old_api
    assert replacement.api.poll() is None
    assert replacement.daemon.poll() is None


def test_paused_step_job_blocks_drained_bundle_restart(tmp_path, monkeypatch) -> None:
    state = manager.ManagerState(tmp_path, "python")
    daemon = _Process(["daemon"])
    api = _Process(["api"])
    bundle = manager.ServiceBundle(
        api=api,
        daemon=daemon,
        socket_path=tmp_path / "jobs.sock",
        deployment_id="test",
    )
    state.processes[state.key(tmp_path)] = bundle
    actions = []

    def request(current, action):
        actions.append(action)
        if action == "drain":
            return {"paused_jobs": ["step-1"], "active_planners": 0, "active_executors": 1}
        return {"paused_jobs": [], "active_planners": 0, "active_executors": 0}

    monkeypatch.setattr(state, "_daemon_request", request)
    with pytest.raises(RuntimeError, match="paused step jobs"):
        state.restart_bundle(tmp_path, 8135)
    assert actions == ["drain", "resume"]


def test_manager_starts_and_stops_vibe_on_fixed_port(tmp_path, monkeypatch) -> None:
    vibe_root = tmp_path / "Vibe-Trading-Integration"
    executable = vibe_root / ".conda" / "bin" / "vibe-trading"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="ascii")
    created = []

    def fake_popen(command, **kwargs):
        process = _Process(command)
        created.append((process, kwargs))
        return process

    monkeypatch.setattr(manager, "VIBE_TRADING_ROOT", vibe_root)
    monkeypatch.setattr(manager, "port_in_use", lambda port: False)
    monkeypatch.setattr(manager.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        manager.ManagerState,
        "_terminate",
        staticmethod(lambda process: setattr(process, "returncode", 0)),
    )
    state = manager.ManagerState(tmp_path, "python")

    message = state.start_vibe()

    assert "started Vibe-Trading" in message
    assert state.vibe_running()
    assert created[0][0].command == [
        str(executable),
        "serve",
        "--host", "127.0.0.1",
        "--port", "7899",
    ]
    assert created[0][1]["cwd"] == vibe_root
    assert state.stop_vibe() == "stopped Vibe-Trading"
    assert not state.vibe_running()


def test_worktree_api_exposes_vibe_status(tmp_path, monkeypatch) -> None:
    state = manager.ManagerState(tmp_path, "python")
    state.capability_path.write_text("test-capability", encoding="ascii")
    monkeypatch.setattr(state, "worktrees", lambda: [])
    monkeypatch.setattr(state, "vibe_running", lambda: False)
    monkeypatch.setattr(manager, "port_in_use", lambda _port: False)

    with _running_manager(state) as base_url:
        request = Request(
            f"{base_url}/api/worktrees",
            headers={"Authorization": "Bearer test-capability"},
        )
        with urlopen(request) as response:
            payload = json.loads(response.read())

    assert payload["vibe_trading"] == {
        "instance_id": "service-vibe-trading",
        "port": 7899,
        "running": False,
        "port_in_use": False,
    }
