from __future__ import annotations

import os
import hashlib
import json
import socket
import sys
import threading
import base64
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pytest

from scripts import worktree_flask_manager as manager
from tools.cli.release.research_reporting.public_research.library import PublicResearchLibrary


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
    tmp_path, monkeypatch
) -> None:
    observed = {}

    class _Server:
        def __init__(self, address, handler):
            observed["address"] = address

        def serve_forever(self):
            return None

        def server_close(self):
            return None

    monkeypatch.setattr(manager, "ThreadingHTTPServer", _Server)
    monkeypatch.setattr(manager.ManagerState, "stop_all", lambda self: None)
    monkeypatch.setattr(manager.webbrowser, "open", lambda _url: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["worktree_flask_manager.py", "--repo", str(tmp_path), "--no-browser"],
    )

    assert manager.main() == 0
    assert observed["address"] == ("0.0.0.0", 7998)


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


def test_job_detail_and_artifacts_share_manager_gateway_paths(
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
        if values["path"].endswith("/artifacts/archive"):
            return manager.GatewayResponse(
                status=200,
                body=b"PK\x03\x04test",
                content_type="application/zip",
                content_disposition='attachment; filename="job-test.zip"',
            )
        return manager.GatewayResponse(
            status=200,
            body=b'{"success":true,"job_id":"job-1"}',
            content_type="application/json",
        )

    monkeypatch.setattr(state.gateway, "request", request)
    headers = {"Authorization": "Bearer user-token"}
    with _running_manager(state) as base_url:
        with urlopen(Request(
            f"{base_url}/api/jobs/job-1?port=8141", headers=headers,
        )) as response:
            detail = json.loads(response.read())
        with urlopen(Request(
            f"{base_url}/api/jobs/job-1/artifacts/archive?port=8141",
            headers=headers,
        )) as response:
            archive = response.read()

    assert detail["job_id"] == "job-1"
    assert detail["port"] == 8141
    assert archive.startswith(b"PK")
    assert [item["path"] for item in calls] == [
        "/api/jobs/job-1",
        "/api/jobs/job-1/artifacts/archive",
    ]
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


def test_anonymous_manager_gateway_allows_preview_but_not_artifact_download(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(tmp_path, "python")
    monkeypatch.setattr(state, "service_ports", lambda: [8141])
    calls = []

    def request(**values):
        calls.append(values)
        if values["path"].endswith("/preview"):
            return manager.GatewayResponse(
                status=200,
                body=b"<svg/>",
                content_type="image/svg+xml",
                content_disposition='inline; filename="equity_curve_report.svg"',
            )
        return manager.GatewayResponse(
            status=200,
            body=b"download",
            content_type="image/svg+xml",
            content_disposition='attachment; filename="equity_curve_report.svg"',
        )

    monkeypatch.setattr(state.gateway, "request", request)
    with _running_manager(state) as base_url:
        with urlopen(
            f"{base_url}/api/jobs/job-1/artifacts/equity_curve_report/preview",
        ) as response:
            assert response.read() == b"<svg/>"
            assert response.headers["Content-Disposition"].startswith("inline;")
        with pytest.raises(HTTPError) as denied:
            urlopen(
                f"{base_url}/api/jobs/job-1/artifacts/equity_curve_report",
            )
        assert denied.value.code == 401

    assert calls == [{
        "port": 8141,
        "path": "/api/jobs/job-1/artifacts/equity_curve_report/preview",
        "principal": "__public_jobs__",
        "method": "GET",
    }]


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

    assert payload["jobs"] == [{"job_id": "job-public", "updated_at": 2.0, "port": 8141}]
    assert payload["has_more"] is False
    assert payload["next_cursor"] is None
    assert payload["total"] == 1
    assert calls == [(
        8141,
        "/api/jobs?scope=server&limit=20",
        "__public_jobs__",
    )]


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
        "job-8141", "job-8176",
    ]
    assert [job["port"] for job in payload["jobs"]] == [8141, 8176]
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
    state = manager.ManagerState(tmp_path, "python", data_root=tmp_path)
    with _running_manager(state) as base_url:
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
    state = manager.ManagerState(tmp_path, "python", data_root=tmp_path)
    with _running_manager(state) as base_url:
        with urlopen(
            f"{base_url}/api/public-research/{result['publication_id']}"
            f"/local-resources/{resource_id}"
        ) as response:
            assert response.read() == raw
            assert "attachment" in response.headers["Content-Disposition"]


def test_local_research_resource_route_is_owner_scoped_and_preserves_filename(
    tmp_path, monkeypatch,
):
    state = manager.ManagerState(tmp_path, "python", data_root=tmp_path)
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
    state = manager.ManagerState(tmp_path, "python")
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
    state = manager.ManagerState(tmp_path, "python", data_root=tmp_path)
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
            f"{base_url}/api/public-research/publish",
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
            f"{base_url}/api/public-research/revoke",
            data=json.dumps({"publication_id": published["publication_id"]}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(revoke) as response:
            assert json.loads(response.read())["status"] == "revoked"
        with urlopen(f"{base_url}/api/public-research") as response:
            assert json.loads(response.read())["reports"] == []


def test_manager_session_survives_restart_without_storing_raw_token(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(
        manager, "_authenticate_user", lambda _username, _password: (
            "admin@1", "super_admin",
        ),
    )
    first = manager.ManagerState(tmp_path, "python")
    token, _, _ = first.login("admin@1", "password")

    payload = first.sessions_path.read_text(encoding="utf-8")
    assert token not in payload
    assert first.sessions_path.stat().st_mode & 0o777 == 0o600

    restarted = manager.ManagerState(tmp_path, "python")
    assert restarted.session(token) == {
        "username": "admin@1",
        "role": "super_admin",
        "capabilities": {"manager": True, "research": True},
    }
    payload = json.loads(restarted.sessions_path.read_text(encoding="utf-8"))
    expires_at = next(iter(payload["sessions"].values()))["expires_at"]
    assert expires_at - manager.time.time() > 29 * 24 * 60 * 60


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
    state = manager.ManagerState(tmp_path, "python")
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


def test_remote_unified_shell_is_public_but_manager_page_is_local_only(
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

    assert denied.value.code == 403
    assert "localhost required" in denied.value.read().decode()


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


def test_manager_page_allows_loopback_browser_without_leaking_paths(
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
        with urlopen(f"{base_url}/manager-legacy") as response:
            body = response.read().decode("utf-8")

    assert str(source) not in body
    assert str(manager.VIBE_TRADING_ROOT) not in body
    assert 'name="path"' not in body
    assert 'name="port"' not in body
    assert 'name="instance_id"' in body


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


def test_cleanup_detached_worktrees_removes_snapshots_and_prunes(tmp_path, monkeypatch) -> None:
    detached = tmp_path / "detached"
    detached.mkdir()
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


def test_cleanup_detached_worktrees_leaves_missing_paths_to_prune(tmp_path, monkeypatch) -> None:
    missing = tmp_path / "missing-detached"
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


def test_manager_page_exposes_vibe_controls(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(manager.ManagerState, "worktrees", lambda self: [])
    monkeypatch.setattr(manager, "port_in_use", lambda port: False)
    state = manager.ManagerState(tmp_path, "python")

    body = manager.page(state).decode()

    assert "Vibe-Trading" in body
    assert "http://localhost:7899/" in body
    assert 'action="/vibe/start"' in body
    assert 'action="/vibe/stop"' in body
