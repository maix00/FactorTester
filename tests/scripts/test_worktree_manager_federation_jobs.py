"""Focused federation behavior tests."""

from __future__ import annotations

import json
import threading
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
        "limit": 20, "_allow_federation": False, **expected,
    }
    assert observed["remote"] == {
        "requester_server_id": "local-feat", "principal": "alice",
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
    server = manager.ThreadingHTTPServer(
        ("127.0.0.1", 0),
        peer_control_handler(state),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        request = Request(
            f"{base_url}/api/federation/jobs/query",
            data=json.dumps({
                "requester_server_id": "local-feat",
                "principal": "alice",
                "scope": "mine",
                "page": 1,
                "limit": 20,
            }).encode(),
            headers={
                "Authorization": "Bearer proxy-token",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request) as response:
            value = json.loads(response.read())
        assert response.status == 200
        assert value["source_server_id"] == "remote-main"
        assert calls == [{
            "principal": "alice",
            "scope": "mine",
            "page": 1,
            "limit": 20,
            "_allow_federation": False,
        }]
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
        page=2,
        limit=20,
    )

    assert local_calls == [{
        "principal": "alice",
        "scope": "subordinates",
        "username": "bob",
        "page": 1,
        "limit": 40,
        "_allow_federation": False,
    }]
    assert payload["page"] == 2
    assert payload["jobs"] == []
    assert payload["total"] == 2
    assert payload["total_pages"] == 1
