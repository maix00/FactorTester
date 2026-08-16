from __future__ import annotations

import hashlib
import json
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.request import Request, urlopen

from server.manager import runtime as manager
from server.manager.data_plane.context import DataPlaneRuntime
from server.manager.data_plane.local_runs import LocalRunArtifactOriginAdapter
from server.manager.data_plane.server import ClientDataPlaneHTTPServer
from server.manager.objects.origin import ObjectOriginRegistry


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


def _local_run_payload() -> dict:
    return {
        "local_job_id": "local-7997",
        "title": "本地测试",
        "kind": "ic_test",
        "status": "succeeded",
        "execution_mode": "local",
        "created_at": 90.0,
        "updated_at": 100.0,
        "requirements": [{"product_ref": "ALPHA", "frequency": "1d"}],
        "summary": {"ic_mean": 0.12},
        "artifact_manifest": [{
            "name": "chart.png",
            "file_name": "chart.png",
            "role": "output",
            "content_type": "image/png",
            "size_bytes": 3,
            "content_hash": hashlib.sha256(b"abc").hexdigest(),
            "upload_state": "local_only",
        }],
    }


def test_local_artifact_requires_explicit_7997_upload_before_download(tmp_path: Path) -> None:
    state = manager.ManagerState(
        tmp_path / "repo",
        "python",
        server_id="public-1",
        state_root=tmp_path / "manager-state",
    )
    state._sessions[state._token_hash("user-token")] = (
        "alice", "user", float("inf"),
    )
    state.local_run_projection.upsert("alice", _local_run_payload())
    runtime = DataPlaneRuntime(
        server_id=state.server_id,
        transfer_database=state.transfer_database_path,
        staging_root=state.transfer_submission_root,
        origin_resolver=ObjectOriginRegistry(
            adapters={
                "local_run_artifact": LocalRunArtifactOriginAdapter(
                    database=state.state_root / "local-run-projection.sqlite",
                    submission_root=state.transfer_submission_root,
                ),
            },
        ),
    )
    data_server = ClientDataPlaneHTTPServer(
        ("127.0.0.1", 0), runtime=runtime,
    )
    state.configure_data_plane(
        client_host="127.0.0.1",
        client_port=data_server.server_address[1],
        client_control_endpoint="http://127.0.0.1:7998",
        client_data_endpoint=(
            f"http://127.0.0.1:{data_server.server_address[1]}"
        ),
    )
    manager.Handler.state = state
    manager_server = manager.ThreadingHTTPServer(
        ("127.0.0.1", 0), manager.Handler,
    )
    digest = hashlib.sha256(b"abc").hexdigest()

    with _running(data_server), _running(manager_server) as endpoint:
        access_request = Request(
            endpoint + "/api/client/local-runs/artifacts/access",
            data=json.dumps({
                "local_job_id": "local-7997",
                "name": "chart.png",
                "size_bytes": 3,
                "content_hash": digest,
            }).encode(),
            method="POST",
            headers={
                "Authorization": "Bearer user-token",
                "Content-Type": "application/json",
            },
        )
        with urlopen(access_request) as response:
            access = json.loads(response.read())["access"]
        with urlopen(Request(
            access["url"],
            data=b"abc",
            method="PUT",
            headers={
                "Authorization": f"Bearer {access['bearer']}",
                "Content-Type": "image/png",
            },
        )) as response:
            assert response.status == 201

        complete_request = Request(
            endpoint + "/api/client/local-runs/artifacts/complete",
            data=json.dumps({
                "local_job_id": "local-7997",
                "name": "chart.png",
                "transfer_id": access["transfer_id"],
            }).encode(),
            method="POST",
            headers={
                "Authorization": "Bearer user-token",
                "Content-Type": "application/json",
            },
        )
        with urlopen(complete_request) as response:
            assert response.status == 200

        detail_request = Request(
            endpoint + "/api/jobs/local-7997",
            headers={"Authorization": "Bearer user-token"},
        )
        with urlopen(detail_request) as response:
            detail = json.loads(response.read())
        assert detail["raw_artifacts_remote"] is True
        assert detail["task_detail"]["artifacts"][0]["state"] == "active"

        download_access_request = Request(
            endpoint + "/api/jobs/local-7997/artifacts/chart.png/access",
            data=b"",
            method="POST",
            headers={"Authorization": "Bearer user-token"},
        )
        with urlopen(download_access_request) as response:
            download = json.loads(response.read())["access"]
        with urlopen(Request(
            download["url"],
            headers={"Authorization": f"Bearer {download['bearer']}"},
        )) as response:
            assert response.read() == b"abc"

    artifact = state.local_run_projection.get(
        "alice", "local-7997",
    )["task_detail"]["artifacts"][0]
    assert artifact["upload_state"] == "uploaded"
