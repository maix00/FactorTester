from __future__ import annotations

import hashlib
import json
import threading
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from server.manager import runtime as manager
from server.manager.data_plane.context import DataPlaneRuntime
from server.manager.data_plane.server import ClientDataPlaneHTTPServer
from server.manager.domain.federation import ServiceRoute


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
    monkeypatch.setattr(
        state,
        "route_json",
        lambda *_args, **_values: {
            "success": True,
            "artifacts": [{
                "name": "result.bin",
                "file_name": "result.bin",
                "content_type": "image/svg+xml",
                "size_bytes": len(raw),
                "content_hash": digest,
                "state": "active",
            }],
        },
    )
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
        state,
        "route_json",
        lambda *_args, **_values: {
            "success": True,
            "artifacts": [{
                "name": "result.bin",
                "file_name": "result.bin",
                "content_type": "application/octet-stream",
                "size_bytes": 6,
                "content_hash": hashlib.sha256(b"result").hexdigest(),
                "state": "active",
            }],
        },
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
        state,
        "route_json",
        lambda *_args, **_values: {
            "success": True,
            "artifacts": [{
                "name": "factor_source.py",
                "file_name": "factor_source.py",
                "artifact_role": "input",
                "content_type": "text/x-python",
                "size_bytes": 6,
                "content_hash": hashlib.sha256(b"secret").hexdigest(),
                "state": "active",
            }],
        },
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
