from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.request import Request, urlopen

from server.manager import runtime as manager
from server.manager.services.agent_workspace import ensure_server_profile_workspace
from tools.cli.release.research_reporting.workspace import initialize_work_package

PRINCIPAL = "GTHT@MaxJJW@392452984564"


def test_server_research_routes_read_owner_report(tmp_path: Path):
    data_root = tmp_path / "data"
    state = manager.ManagerState(
        tmp_path,
        "python",
        data_root=data_root,
        session_db_path=tmp_path / "manager.sqlite",
    )
    profile_id = "profile-main"
    state.agent_profiles.bind_runtime(
        PRINCIPAL,
        profile_id,
        runtime_kind="server",
        executor_id=state.server_id,
    )
    workspace = ensure_server_profile_workspace(data_root, PRINCIPAL, profile_id)
    initialize_work_package(
        workspace_root=workspace,
        work_package_id="report-one",
        branch_id="main",
        workspace_id=profile_id,
        title="路由报告",
        branch_ref="graph-branch:report-one:main",
    )
    token = "server-research-token"
    state._sessions[state._token_hash(token)] = (
        PRINCIPAL, "user", float("inf"),
    )
    manager.Handler.state = state
    server = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        request = Request(
            f"{base}/api/server-research",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urlopen(request) as response:
            listing = json.loads(response.read())
        assert listing["success"] is True
        assert listing["research"][0]["build_source"] == "server_agent"

        server_ref = listing["research"][0]["server_ref"]
        request = Request(
            f"{base}/api/server-research/{server_ref}/index",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urlopen(request) as response:
            index = json.loads(response.read())
        assert index["access"]["sharing_state"] == "not_shared"

        request = Request(
            f"{base}/api/research-publications/settings",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urlopen(request) as response:
            settings = json.loads(response.read())
        assert settings["reports"][0]["build_source"] == "server_agent"
        assert settings["reports"][0]["sharing_state"] == "not_shared"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
