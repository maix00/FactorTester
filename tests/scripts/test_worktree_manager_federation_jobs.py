"""Focused federation behavior tests."""

from __future__ import annotations

import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from server.manager import runtime as manager
from server.manager.http.peer_handler import peer_control_handler
from tests.federation_fixtures import federation_registration as _registration


def test_cross_server_jobs_are_fetched_on_demand_without_local_projection_sync(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(
        tmp_path / "cross-repo",
        "python",
        server_role="feat",
        server_id="local-feat",
        state_root=tmp_path / "cross-state",
    )
    state.federation_registry.register(
        _registration("remote-main", latency_ms=8, load=1),
    )
    local_calls = []

    def local_jobs(**kwargs):
        local_calls.append(kwargs)
        return {
            "jobs": [{
                "job_id": "local-job", "port": 8141,
                "owner": "alice", "updated_at": "2026-08-12T00:02:00Z",
            }],
            "total": 1, "has_more": False,
        }

    monkeypatch.setattr(state, "aggregate_account_jobs", local_jobs)
    monkeypatch.setattr(
        state,
        "_federation_manager_routes",
        lambda: [state.federation_registry.find(server_id="remote-main", port=8000)],
    )

    class Gateway:
        def __init__(self):
            self.calls = []

        def query_jobs(self, route, **kwargs):
            assert route.server_id == "remote-main"
            assert kwargs["scope"] == "mine"
            self.calls.append(kwargs)
            return {
                "jobs": [{
                    "job_id": "remote-job", "port": 8000,
                    "owner": "alice", "updated_at": "2026-08-12T00:03:00Z",
                }],
                "total": 1, "has_more": False,
            }

    gateway = Gateway()
    state.federation_gateway = gateway
    payload = state.aggregate_cross_server_jobs(
        principal="alice", source_scope="mine", limit=20,
        delegated_user_token="verified-alice-token",
    )

    assert payload["sync_mode"] == "on_demand"
    assert [item["job_id"] for item in payload["jobs"]] == [
        "remote-job", "local-job",
    ]
    assert [item["server_id"] for item in payload["jobs"]] == [
        "remote-main", "local-feat",
    ]
    assert [item["execution_server_id"] for item in payload["jobs"]] == [
        "remote-main", "local-feat",
    ]
    assert [item["execution_port"] for item in payload["jobs"]] == [
        8000, 8141,
    ]
    assert local_calls[0]["_allow_federation"] is False

    cached = state.aggregate_cross_server_jobs(
        principal="alice", source_scope="mine", limit=20,
        delegated_user_token="verified-alice-token",
    )
    assert cached["sync_mode"] == "cache"
    assert gateway.calls[0]["limit"] == 20


def test_cross_server_jobs_query_local_and_peer_sources_concurrently(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(
        tmp_path / "parallel-repo",
        "python",
        server_role="feat",
        server_id="local-feat",
        state_root=tmp_path / "parallel-state",
    )
    state.federation_registry.register(
        _registration("remote-main", latency_ms=8, load=1),
    )
    route = state.federation_registry.find(
        server_id="remote-main", port=8000,
    )
    monkeypatch.setattr(state, "_federation_manager_routes", lambda: [route])
    local_started = threading.Event()
    peer_started = threading.Event()

    def local_jobs(**_kwargs):
        local_started.set()
        assert peer_started.wait(timeout=0.5), "peer query was not started in parallel"
        return {
            "jobs": [{"job_id": "local-job", "updated_at": 1.0}],
            "total": 1,
            "has_more": False,
        }

    monkeypatch.setattr(state, "aggregate_account_jobs", local_jobs)

    class Gateway:
        def query_jobs(self, _route, **_kwargs):
            peer_started.set()
            assert local_started.wait(timeout=0.5), "local query was not started in parallel"
            return {
                "jobs": [{"job_id": "remote-job", "updated_at": 2.0}],
                "total": 1,
                "has_more": False,
            }

    state.federation_gateway = Gateway()
    payload = state.aggregate_cross_server_jobs(
        principal="alice", source_scope="mine", limit=20,
        delegated_user_token="verified-alice-token",
    )

    assert [item["job_id"] for item in payload["jobs"]] == [
        "remote-job", "local-job",
    ]


def test_cross_server_visible_object_jobs_forward_stable_filter(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(
        tmp_path / "visible-repo",
        "python",
        server_role="feat",
        server_id="local-feat",
        state_root=tmp_path / "visible-state",
    )
    state.federation_registry.register(
        _registration("remote-main", latency_ms=8, load=1),
    )
    route = state.federation_registry.find(
        server_id="remote-main", port=8000,
    )
    monkeypatch.setattr(state, "_federation_manager_routes", lambda: [route])
    calls = []

    def local_jobs(**kwargs):
        calls.append(("local", kwargs))
        return {"jobs": [], "total": 0, "has_more": False}

    monkeypatch.setattr(state, "aggregate_account_jobs", local_jobs)

    class Gateway:
        def query_jobs(self, _route, **kwargs):
            calls.append(("remote", kwargs))
            return {"jobs": [], "total": 0, "has_more": False}

    state.federation_gateway = Gateway()
    state.aggregate_cross_server_jobs(
        principal="alice",
        source_scope="visible",
        delegated_user_token="verified-alice-token",
        limit=20,
        object_kind="family",
        object_owner_ref="principal:alice",
        object_alias="Momentum",
    )

    expected = {
        "object_kind": "family",
        "object_owner_ref": "principal:alice",
        "object_alias": "Momentum",
    }
    observed = dict(calls)
    assert observed["local"] == {
        "principal": "alice", "scope": "visible", "page": 1,
        "limit": 20, "_allow_federation": False,
        "delegated_user_token": "verified-alice-token", **expected,
    }
    assert observed["remote"] == {
        "requester_server_id": "local-feat", "principal": "alice",
        "delegated_user_token": "verified-alice-token",
        "scope": "visible", "page": 1, "limit": 20, "username": "",
        **expected,
    }


def test_peer_job_query_endpoint_is_authenticated_and_local_only(tmp_path, monkeypatch) -> None:
    state = manager.ManagerState(
        tmp_path / "query-repo",
        "python",
        server_role="main",
        server_id="remote-main",
        state_root=tmp_path / "query-state",
    )
    state.federation_proxy_path.write_text("proxy-token", encoding="ascii")
    calls = []

    def local_jobs(**kwargs):
        calls.append(kwargs)
        return {"jobs": [{"job_id": "remote-job", "port": 8000}], "total": 1}

    monkeypatch.setattr(state, "aggregate_account_jobs", local_jobs)
    server_calls = []
    monkeypatch.setattr(state, "aggregate_server_jobs", lambda **kwargs: (
        server_calls.append(kwargs) or {"jobs": [], "total": 0, "has_more": False}
    ))
    identity = {
        "username": "alice", "keycloak_roles": (),
        "keycloak_groups": (
            "/traderesearch/admin-scopes/organizations/org-1/organization-admins",
        ),
    }
    monkeypatch.setattr(state, "session", lambda token: identity if token == "verified-alice-token" else None)
    from server.identity import keycloak_directory

    monkeypatch.setattr(
        keycloak_directory,
        "managed_users_for_claims",
        lambda **_kwargs: [{"username": "bob"}],
    )
    server = manager.ThreadingHTTPServer(
        ("127.0.0.1", 0),
        peer_control_handler(state),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"

    def query(*, principal="alice", scope="mine", username="", cursor=""):
        payload = {
            "requester_server_id": "local-feat",
            "principal": principal,
            "delegated_user_token": "verified-alice-token",
            "scope": scope,
            "page": 1,
            "limit": 20,
        }
        if username:
            payload["username"] = username
        if cursor:
            payload["cursor"] = cursor
        request = Request(
            f"{base_url}/api/federation/jobs/query",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": "Bearer proxy-token",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    try:
        status, value = query()
        assert status == 200
        assert value["source_server_id"] == "remote-main"
        assert calls == [{
            "principal": "alice",
            "scope": "mine",
            "page": 1,
            "limit": 20,
            "delegated_user_token": "verified-alice-token",
            "_allow_federation": False,
        }]

        status, forged = query(principal="mallory")
        assert status == 403
        assert "does not match" in forged["error"]

        status, unrelated_owner = query(scope="mine", username="charlie")
        assert status == 403
        assert "authenticated principal" in unrelated_owner["error"]
        assert len(calls) == 1

        status, unrelated = query(
            scope="subordinates", username="charlie",
        )
        assert status == 403
        assert "outside the Keycloak managed hierarchy" in unrelated["error"]
        assert len(calls) == 1

        identity["keycloak_roles"] = ("admin_console:manage",)
        status, value = query(scope="server", cursor="continuation")
        assert status == 200
        assert server_calls == [{"principal": "alice", "cursor": "continuation", "limit": 20,
                                 "delegated_user_token": "verified-alice-token", "_allow_federation": False}]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_cross_server_subordinate_jobs_forward_user_and_global_page(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(
        tmp_path / "subordinate-repo",
        "python",
        server_role="feat",
        server_id="local-feat",
        state_root=tmp_path / "subordinate-state",
    )
    remote = _registration("remote-main", latency_ms=8, load=1)
    state.federation_registry.register(remote)
    route = state.federation_registry.find(
        server_id="remote-main", port=8000,
    )
    monkeypatch.setattr(state, "_federation_manager_routes", lambda: [route])
    local_calls = []

    def local_jobs(**kwargs):
        local_calls.append(kwargs)
        return {
            "jobs": [{
                "job_id": "local-subordinate-job",
                "port": 8141,
                "updated_at": "2026-08-12T00:02:00Z",
            }],
            "total": 1,
            "has_more": False,
        }

    monkeypatch.setattr(state, "aggregate_account_jobs", local_jobs)

    class Gateway:
        def query_jobs(self, route, **kwargs):
            assert route.server_id == "remote-main"
            assert kwargs == {
                "requester_server_id": "local-feat",
                "principal": "alice",
                "delegated_user_token": "verified-alice-token",
                "scope": "subordinates",
                "page": 1,
                "limit": 40,
                "username": "bob",
            }
            return {
                "jobs": [{
                    "job_id": "remote-subordinate-job",
                    "port": 8000,
                    "updated_at": "2026-08-12T00:03:00Z",
                }],
                "total": 1,
                "has_more": False,
            }

    state.federation_gateway = Gateway()
    payload = state.aggregate_cross_server_jobs(
        principal="alice",
        source_scope="subordinates",
        username="bob",
        delegated_user_token="verified-alice-token",
        page=2,
        limit=20,
    )

    assert local_calls == [{
        "principal": "alice",
        "scope": "subordinates",
        "username": "bob",
        "page": 1,
        "limit": 40,
        "delegated_user_token": "verified-alice-token",
        "_allow_federation": False,
    }]
    assert payload["page"] == 2
    assert payload["jobs"] == []
    assert payload["total"] == 2
    assert payload["total_pages"] == 1


def test_cross_server_history_pages_merge_beyond_first_hundred(tmp_path, monkeypatch):
    state = manager.ManagerState(
        tmp_path / "history-repo", "python", server_role="feat",
        server_id="local-feat", state_root=tmp_path / "history-state",
    )
    state.federation_registry.register(_registration("remote-main", latency_ms=8, load=1))
    route = state.federation_registry.find(server_id="remote-main", port=8000)
    monkeypatch.setattr(state, "_federation_manager_routes", lambda: [route])
    calls = []
    local = [{"job_id": f"local-{i}", "port": 8141, "updated_at": 1000 - i * 2}
             for i in range(130)]
    remote = [{"job_id": f"remote-{i}", "port": 8000, "updated_at": 999 - i * 2}
              for i in range(130)]

    def page_of(rows, scope, kwargs):
        page, limit = kwargs["page"], kwargs["limit"]
        calls.append((scope, page, limit))
        start = (page - 1) * limit
        return {"jobs": rows[start:start + limit], "total": len(rows),
                "has_more": start + limit < len(rows)}

    monkeypatch.setattr(state, "aggregate_account_jobs", lambda **kw: page_of(local, "local", kw))

    class Gateway:
        def query_jobs(self, _route, **kw):
            return page_of(remote, "remote", kw)

    state.federation_gateway = Gateway()
    payload = state.aggregate_cross_server_jobs(
        principal="alice", source_scope="mine", delegated_user_token="verified-alice-token",
        page=8, limit=30,
    )
    expected = sorted(local + remote, key=lambda item: item["updated_at"], reverse=True)[210:240]
    assert [item["job_id"] for item in payload["jobs"]] == [item["job_id"] for item in expected]
    assert payload["total"] == 260 and payload["has_more"] and not payload["partial"]
    assert sorted(calls) == [("local", 1, 100), ("local", 2, 100),
                             ("remote", 1, 100), ("remote", 2, 100)]


def test_single_manager_history_seeks_requested_page(tmp_path, monkeypatch):
    state = manager.ManagerState(tmp_path / "history-repo", "python")
    monkeypatch.setattr(state, "_federation_manager_routes", lambda: [])
    calls = []

    def local_jobs(**kwargs):
        calls.append((kwargs["page"], kwargs["limit"]))
        assert kwargs["delegated_user_token"] == "verified-token"
        return {"jobs": [{"job_id": "page-two", "port": 8141, "updated_at": 1}],
                "page": 2, "total": 591, "has_more": True}

    monkeypatch.setattr(state, "aggregate_account_jobs", local_jobs)
    payload = state.aggregate_cross_server_jobs(
        principal="alice", source_scope="mine", delegated_user_token="verified-token",
        page=2, limit=100,
    )
    assert calls == [(2, 100)]
    assert [job["job_id"] for job in payload["jobs"]] == ["page-two"]
    assert payload["total"] == 591 and payload["has_more"] and not payload["partial"]


def test_server_history_reports_partial_if_source_does_not_advance_cursor(tmp_path, monkeypatch):
    state = manager.ManagerState(tmp_path / "history-repo", "python")
    monkeypatch.setattr(state, "_federation_manager_routes", lambda: [])
    calls = []

    def local_jobs(**kwargs):
        calls.append(kwargs["cursor"])
        return {"jobs": [{"job_id": "a", "updated_at": 2},
                         {"job_id": "b", "updated_at": 1}],
                "total": 4, "has_more": True, "next_cursor": "same"}

    monkeypatch.setattr(state, "aggregate_server_jobs", local_jobs)
    payload = state.aggregate_cross_server_jobs(
        principal="admin", source_scope="server", delegated_user_token="verified-admin-token",
        page=2, limit=1,
    )
    assert calls == ["", "same"]
    assert payload["partial"] is True
    assert payload["sources"][0]["error"] == "source did not advance pagination"
