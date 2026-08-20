from __future__ import annotations

import hashlib
import json
import threading
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pytest

import settings as Settings
from server.jobs.models import JobRecord
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus
from server.manager import runtime as manager
from server.manager.data_plane.context import DataPlaneRuntime
from server.manager.data_plane.server import ClientDataPlaneHTTPServer
from server.manager.domain.federation import ServiceRoute


@pytest.fixture(autouse=True)
def _isolated_manager_sqlite(tmp_path, monkeypatch):
    """Never let HTTP transfer tests write the running Manager's database."""
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "manager.sqlite")


@contextmanager
def _running(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_manager_issues_public_7997_capability_for_local_artifact(
    tmp_path, monkeypatch,
) -> None:
    raw = b'<svg xmlns="http://www.w3.org/2000/svg"><title>curve</title></svg>'
    digest = hashlib.sha256(raw).hexdigest()
    origin = tmp_path / "result.bin"
    origin.write_bytes(raw)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "jobs.sqlite")
    repository = JobRepository()
    repository.create(JobRecord(
        job_id="job-1", run_id="run-1", owner="alice",
        workspace_id="workspace", kind="backtest",
        status=JobStatus.SUBMITTED, retention_mode="full", job_spec={},
    ))
    repository.record_artifact(
        job_id="job-1", name="result.bin", relative_path="job-1/result.bin",
        content_type="image/svg+xml", content_hash=digest,
        size_bytes=len(raw),
    )
    state = manager.ManagerState(
        tmp_path / "repo",
        "python",
        server_id="local-feat",
        state_root=tmp_path / "manager-state",
    )
    state._sessions[state._token_hash("user-token")] = (
        "alice", "user", float("inf"),
    )
    data_runtime = DataPlaneRuntime(
        server_id=state.server_id,
        transfer_database=state.transfer_database_path,
        staging_root=tmp_path / "incoming",
        origin_resolver=lambda _transfer: origin,
    )
    data_server = ClientDataPlaneHTTPServer(
        ("127.0.0.1", 0), runtime=data_runtime,
    )
    data_endpoint = f"http://127.0.0.1:{data_server.server_address[1]}"
    state.configure_data_plane(
        client_host="127.0.0.1",
        client_port=data_server.server_address[1],
        client_control_endpoint="http://127.0.0.1:7998",
        client_data_endpoint=data_endpoint,
    )
    route = ServiceRoute(
        server_id=state.server_id,
        role="feat",
        branch="feat",
        revision="test",
        port=8141,
    )
    monkeypatch.setattr(state, "route_for", lambda **_values: route)
    manager.Handler.state = state
    manager_server = manager.ThreadingHTTPServer(
        ("127.0.0.1", 0), manager.Handler,
    )

    with _running(data_server), _running(manager_server) as manager_endpoint:
        access_request = Request(
            manager_endpoint
            # The stale worker port must not affect retained-artifact access.
            + "/api/jobs/job-1/artifacts/result.bin/access?port=9999",
            data=b"",
            method="POST",
            headers={
                "Authorization": "Bearer user-token",
                "Idempotency-Key": "local-result-download",
            },
        )
        with urlopen(access_request) as response:
            value = json.loads(response.read())

        assert value["access"]["url"].startswith(data_endpoint + "/")
        with pytest.raises(HTTPError) as session_rejected:
            urlopen(Request(
                value["access"]["url"],
                headers={"Authorization": "Bearer user-token"},
            ))
        assert session_rejected.value.code == 403

        with urlopen(Request(
            value["access"]["url"],
            headers={
                "Authorization": f"Bearer {value['access']['bearer']}",
            },
        )) as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == "image/svg+xml"
            assert response.read() == raw


@pytest.mark.parametrize(
    ("is_super_admin", "children"),
    ((True, set()), (False, {"bob"})),
)
def test_authorized_account_artifact_read_uses_indexed_job_owner(
    is_super_admin, children,
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(
        tmp_path / "repo",
        "python",
        server_id="local-feat",
        state_root=tmp_path / "manager-state",
    )
    state._sessions[state._token_hash("user-token")] = (
        "alice", "user", float("inf"),
    )
    route = ServiceRoute(
        server_id=state.server_id,
        role="feat",
        branch="feat",
        revision="test",
        port=8141,
    )
    state.job_index.upsert("__public_jobs__", [{
        "job_id": "job-1",
        "owner": "bob",
        "server_id": state.server_id,
        "port": 8141,
        "updated_at": "100",
    }])
    seen_principals: list[str] = []
    prepared: dict[str, object] = {}

    monkeypatch.setattr(
        "server.manager.http.job_public_projection._account_scope",
        lambda _principal: (is_super_admin, children),
    )
    monkeypatch.setattr(state, "route_for", lambda **_values: route)

    def list_artifacts(_catalog, *, job_id, principal):
        seen_principals.append(principal)
        if principal != "bob":
            return []
        return [{
                "name": "equity_curve_report",
                "file_name": "equity_curve_report.svg",
                "content_type": "image/svg+xml",
                "size_bytes": 7,
                "content_hash": hashlib.sha256(b"<svg/>").hexdigest(),
                "state": "active",
            }]

    monkeypatch.setattr(
        "server.manager.http.job_transfer_routes.JobArtifactCatalog.list",
        list_artifacts,
    )

    def prepare(**values):
        prepared.update(values)
        return {
            "url": "http://127.0.0.1:7997/v1/transfers/public/download",
            "bearer": "capability",
        }

    monkeypatch.setattr(
        state,
        "prepare_artifact_download",
        prepare,
    )
    manager.Handler.state = state
    server = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)

    with _running(server) as endpoint:
        request = Request(
            endpoint + "/api/jobs/job-1/artifacts/equity_curve_report/access",
            data=b"",
            method="POST",
            headers={
                "Authorization": "Bearer user-token",
                "Idempotency-Key": "public-equity-curve",
            },
        )
        with urlopen(request) as response:
            value = json.loads(response.read())

    assert value["success"] is True
    assert seen_principals == ["alice", "bob"]
    assert prepared["principal"] == "bob"


def test_unrelated_account_cannot_use_public_job_projection(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(
        tmp_path / "repo",
        "python",
        server_id="local-feat",
        state_root=tmp_path / "manager-state",
    )
    state._sessions[state._token_hash("user-token")] = (
        "alice", "user", float("inf"),
    )
    route = ServiceRoute(
        server_id=state.server_id,
        role="feat",
        branch="feat",
        revision="test",
        port=8141,
    )
    state.job_index.upsert("__public_jobs__", [{
        "job_id": "job-1",
        "owner": "bob",
        "server_id": state.server_id,
        "port": 8141,
        "updated_at": "100",
    }])
    seen_principals: list[str] = []
    monkeypatch.setattr(
        "server.manager.http.job_public_projection._account_scope",
        lambda _principal: (False, set()),
    )
    monkeypatch.setattr(state, "route_for", lambda **_values: route)
    monkeypatch.setattr(
        "server.manager.http.job_transfer_routes.JobArtifactCatalog.list",
        lambda _catalog, *, job_id, principal: seen_principals.append(principal)
        or [],
    )
    manager.Handler.state = state
    server = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)

    with _running(server) as endpoint:
        request = Request(
            endpoint + "/api/jobs/job-1/artifacts/equity_curve_report/access",
            data=b"",
            method="POST",
            headers={
                "Authorization": "Bearer user-token",
                "Idempotency-Key": "unrelated-equity-curve",
            },
        )
        with pytest.raises(HTTPError) as denied:
            urlopen(request)

    assert denied.value.code == 404
    assert seen_principals == ["alice"]


def test_job_detail_response_preserves_federated_origin_for_later_artifact_reads(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(
        tmp_path / "detail-repo",
        "python",
        server_id="requesting-manager",
        state_root=tmp_path / "detail-state",
    )
    state._sessions[state._token_hash("user-token")] = (
        "alice", "user", float("inf"),
    )
    route = ServiceRoute(
        server_id="remote-main",
        role="main",
        branch="main",
        revision="remote-revision",
        port=8000,
        remote=True,
        online=True,
    )
    monkeypatch.setattr(
        manager.Handler,
        "_job_routes",
        lambda _handler, _parsed, _principal: [route],
    )
    monkeypatch.setattr(
        state,
        "route_request",
        lambda *_args, **_kwargs: manager.GatewayResponse(
            status=200,
            body=b'{"success":true,"task_detail":{"job":{"job_id":"job-1"}}}',
            content_type="application/json",
        ),
    )
    manager.Handler.state = state
    server = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)

    with _running(server) as endpoint:
        request = Request(
            endpoint + "/api/jobs/job-1",
            headers={"Authorization": "Bearer user-token"},
        )
        with urlopen(request) as response:
            value = json.loads(response.read())

    assert value["server_id"] == "remote-main"
    assert value["execution_server_id"] == "remote-main"
    assert value["execution_port"] == 8000
    assert value["storage_server_id"] == "remote-main"


def test_artifact_route_uses_indexed_storage_server_without_execution_port(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(
        tmp_path / "indexed-repo",
        "python",
        server_id="requesting-manager",
        state_root=tmp_path / "indexed-state",
    )
    state.job_index.upsert("alice", [{
        "job_id": "job-indexed",
        "port": 8141,
        "storage_server_id": "remote-storage",
        "execution_server_id": "remote-storage",
    }])
    selected = ServiceRoute(
        server_id="remote-storage",
        role="feat",
        branch="issue",
        revision="revision",
        port=9123,
        remote=True,
        online=False,
        peer_control_endpoint="http://10.0.0.2:7998",
        proxy_token="peer-token",
    )
    monkeypatch.setattr(
        state,
        "service_routes",
        lambda **_kwargs: [selected],
    )
    manager.Handler.state = state
    handler = object.__new__(manager.Handler)
    parsed = urlparse(
        "/api/jobs/job-indexed/artifacts/equity_curve_report.svg/access"
    )

    routes = handler._job_routes(
        parsed, "alice", for_artifact_storage=True,
    )

    assert routes == [selected]
    assert routes[0].port == 9123
    assert routes[0].port != 8141


def test_remote_artifact_metadata_uses_peer_manager_control_plane(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(
        tmp_path / "repo", "python", server_id="requesting-manager",
        state_root=tmp_path / "manager-state",
    )
    route = ServiceRoute(
        server_id="source-manager", role="main", branch="main",
        revision="revision", port=8000, remote=True, online=False,
        peer_control_endpoint="http://10.0.0.2:7998",
        proxy_token="peer-token",
    )
    calls: list[dict[str, object]] = []

    def public_data(selected, **values):
        calls.append({"route": selected, **values})
        return {"success": True, "artifacts": [{
            "name": "curve.svg", "file_name": "curve.svg",
            "state": "active", "artifact_role": "output",
            "content_type": "image/svg+xml", "size_bytes": 5,
            "content_hash": hashlib.sha256(b"curve").hexdigest(),
        }]}

    monkeypatch.setattr(state.federation_gateway, "public_data", public_data)
    monkeypatch.setattr(
        state, "route_request",
        lambda *_args, **_kwargs: pytest.fail(
            "artifact metadata must not use the business-service proxy"
        ),
    )
    manager.Handler.state = state
    handler = object.__new__(manager.Handler)

    payload = handler._job_artifact_payload(
        route, job_id="job-remote", principal="alice",
    )

    assert payload["artifacts"][0]["name"] == "curve.svg"
    assert calls == [{
        "route": route,
        "kind": "job-artifacts",
        "operation": "list",
        "principal": "alice",
        "payload": {"job_id": "job-remote"},
    }]


def test_artifact_route_can_target_peer_manager_with_no_business_ports(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(
        tmp_path / "repo", "python", server_id="requesting-manager",
        state_root=tmp_path / "manager-state",
    )
    state.job_index.upsert("alice", [{
        "job_id": "job-no-worker",
        "owner": "alice",
        "port": 0,
        "storage_server_id": "source-manager",
    }])
    monkeypatch.setattr(state, "service_routes", lambda **_values: [])
    monkeypatch.setattr(
        state.federation_registry,
        "describe",
        lambda server_id: {
            "server_id": server_id,
            "role": "main",
            "branch": "main",
            "revision": "revision",
            "endpoint": "http://10.0.0.2:7998",
            "proxy_token": "peer-token",
            "transfer_node": {
                "peer_control_endpoint": "http://10.10.0.2:7998",
                "peer_data_endpoint": "http://10.10.0.2:7997",
            },
        },
    )
    manager.Handler.state = state
    handler = object.__new__(manager.Handler)

    routes = handler._job_routes(
        urlparse("/api/jobs/job-no-worker/artifacts/curve.svg/access"),
        "alice",
        for_artifact_storage=True,
    )

    assert len(routes) == 1
    assert routes[0].server_id == "source-manager"
    assert routes[0].port == 0
    assert routes[0].peer_control_endpoint == "http://10.10.0.2:7998"


def test_local_manager_reads_artifact_metadata_without_business_service(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "jobs.sqlite")
    repository = JobRepository()
    repository.create(JobRecord(
        job_id="job-manager-owned",
        run_id="run-manager-owned",
        owner="alice",
        workspace_id="workspace",
        kind="backtest",
        status=JobStatus.SUBMITTED,
        retention_mode="full",
        job_spec={},
    ))
    artifact = repository.record_artifact(
        job_id="job-manager-owned",
        name="curve.svg",
        relative_path="job-manager-owned/curve.svg",
        content_type="image/svg+xml",
        content_hash=hashlib.sha256(b"curve").hexdigest(),
        size_bytes=5,
    )
    state = manager.ManagerState(
        tmp_path / "repo",
        "python",
        server_id="local-feat",
        state_root=tmp_path / "manager-state",
    )
    state.job_index.upsert("alice", [{
        "job_id": "job-manager-owned",
        "owner": "alice",
        "storage_server_id": "local-feat",
    }])
    monkeypatch.setattr(
        state,
        "route_json",
        lambda *_args, **_kwargs: pytest.fail(
            "artifact metadata must not use a business service route"
        ),
    )
    manager.Handler.state = state
    handler = object.__new__(manager.Handler)

    selected = handler._artifact_metadata(
        [ServiceRoute(
            server_id="local-feat",
            role="feat",
            branch="feat",
            revision="test",
            port=0,
        )],
        job_id="job-manager-owned",
        name="curve.svg",
        principal="alice",
    )

    assert selected is not None
    route, metadata, lookup_principal = selected
    assert route.server_id == "local-feat"
    assert metadata["name"] == artifact["name"]
    assert lookup_principal == "alice"


def test_public_artifact_transfer_access_requires_manager_session(tmp_path) -> None:
    state = manager.ManagerState(
        tmp_path / "repo",
        "python",
        server_id="local-feat",
        state_root=tmp_path / "manager-state",
    )
    state.require_login_for_ui = True
    manager.Handler.state = state
    server = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)

    with _running(server) as endpoint:
        request = Request(
            endpoint + "/api/jobs/job-1/artifacts/result.bin/access?port=8141",
            data=b"",
            method="POST",
        )
        with pytest.raises(HTTPError) as denied:
            urlopen(request)

    assert denied.value.code == 401


def test_local_unprotected_manager_uses_anonymous_transfer_principal(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(
        tmp_path / "repo",
        "python",
        server_id="local-feat",
        state_root=tmp_path / "manager-state",
    )
    route = ServiceRoute(
        server_id=state.server_id,
        role="feat",
        branch="feat",
        revision="test",
        port=8141,
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(state, "route_for", lambda **_values: route)
    monkeypatch.setattr(
        "server.manager.http.job_transfer_routes.JobArtifactCatalog.list",
        lambda _catalog, **_values: [{
                "name": "result.bin",
                "file_name": "result.bin",
                "content_type": "application/octet-stream",
                "size_bytes": 6,
                "content_hash": hashlib.sha256(b"result").hexdigest(),
                "state": "active",
            }],
    )

    def prepare(**values):
        captured.update(values)
        return {
            "url": "http://127.0.0.1:7997/v1/transfers/a/download",
            "bearer": "capability",
            "expected_size": 6,
        }

    monkeypatch.setattr(state, "prepare_artifact_download", prepare)
    manager.Handler.state = state
    server = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)

    with _running(server) as endpoint:
        with urlopen(Request(
            endpoint + "/api/jobs/job-1/artifacts/result.bin/access?port=8141",
            data=b"",
            method="POST",
        )) as response:
            value = json.loads(response.read())

    assert value["success"] is True
    assert captured["principal"] == "__public_jobs__"


def test_local_unprotected_manager_does_not_expose_input_artifact(
    tmp_path, monkeypatch,
) -> None:
    state = manager.ManagerState(
        tmp_path / "repo",
        "python",
        server_id="local-feat",
        state_root=tmp_path / "manager-state",
    )
    route = ServiceRoute(
        server_id=state.server_id,
        role="feat",
        branch="feat",
        revision="test",
        port=8141,
    )
    monkeypatch.setattr(state, "route_for", lambda **_values: route)
    monkeypatch.setattr(
        "server.manager.http.job_transfer_routes.JobArtifactCatalog.list",
        lambda _catalog, **_values: [{
                "name": "factor_source.py",
                "file_name": "factor_source.py",
                "artifact_role": "input",
                "content_type": "text/x-python",
                "size_bytes": 6,
                "content_hash": hashlib.sha256(b"secret").hexdigest(),
                "state": "active",
            }],
    )
    manager.Handler.state = state
    server = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)

    with _running(server) as endpoint:
        with pytest.raises(HTTPError) as denied:
            urlopen(Request(
                endpoint
                + "/api/jobs/job-1/artifacts/factor_source.py/access?port=8141",
                data=b"",
                method="POST",
            ))

    assert denied.value.code == 401


def test_manager_issues_public_7997_capability_and_reports_verified_upload(
    tmp_path,
) -> None:
    raw = b"submitted source through explicit transfer access"
    digest = hashlib.sha256(raw).hexdigest()
    state = manager.ManagerState(
        tmp_path / "repo",
        "python",
        server_id="local-feat",
        state_root=tmp_path / "manager-state",
    )
    state._sessions[state._token_hash("user-token")] = (
        "alice", "user", float("inf"),
    )
    data_runtime = DataPlaneRuntime(
        server_id=state.server_id,
        transfer_database=state.transfer_database_path,
        staging_root=state.transfer_submission_root,
        origin_resolver=lambda _transfer: tmp_path / "not-an-origin",
    )
    data_server = ClientDataPlaneHTTPServer(
        ("127.0.0.1", 0), runtime=data_runtime,
    )
    data_endpoint = f"http://127.0.0.1:{data_server.server_address[1]}"
    state.configure_data_plane(
        client_host="127.0.0.1",
        client_port=data_server.server_address[1],
        client_control_endpoint="http://127.0.0.1:7998",
        client_data_endpoint=data_endpoint,
    )
    manager.Handler.state = state
    manager_server = manager.ThreadingHTTPServer(
        ("127.0.0.1", 0), manager.Handler,
    )

    with _running(data_server), _running(manager_server) as manager_endpoint:
        access_request = Request(
            manager_endpoint + "/api/transfers/submissions/access",
            data=json.dumps({
                "job_id": "job-1",
                "name": "source.py",
                "size_bytes": len(raw),
                "sha256": digest,
            }).encode(),
            method="POST",
            headers={
                "Authorization": "Bearer user-token",
                "Content-Type": "application/json",
                "Idempotency-Key": "local-source-upload",
            },
        )
        with urlopen(access_request) as response:
            assert response.status == 201
            value = json.loads(response.read())

        access = value["access"]
        assert access["resume_offset"] == 0
        assert "storage_reference" not in access
        with urlopen(Request(
            access["url"],
            data=raw,
            method="PUT",
            headers={
                "Authorization": f"Bearer {access['bearer']}",
                "Content-Type": "application/octet-stream",
            },
        )) as response:
            assert response.status == 201

        with urlopen(Request(
            manager_endpoint + f"/api/transfers/{access['transfer_id']}",
            headers={"Authorization": "Bearer user-token"},
        )) as response:
            status = json.loads(response.read())

    assert status["transfer"]["status"] == "completed"
    assert status["transfer"]["storage_reference"].startswith(
        "submission:local-feat:"
    )
    transfer = state.transfer_store.require(access["transfer_id"])
    attempt = state.transfer_attempts.latest(transfer.transfer_id)
    assert attempt is not None
    assert data_runtime.destination_path(transfer, attempt).read_bytes() == raw
