from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen

from server.manager import runtime as manager
from server.manager.services.agent_workspace import ensure_server_profile_workspace
from tools.cli.release.research_reporting.workspace import initialize_report_workspace

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
    initialize_report_workspace(
        workspace_root=workspace,
        report_workspace_id="report-one",
        report_id="report-report-one",
        branch_id="main",
        workspace_id=profile_id,
        title="路由报告",
        branch_ref="report-branch:main",
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

        request = Request(
            f"{base}/api/research-publications/publish",
            data=json.dumps({
                "server_ref": server_ref,
                "visibility": "private",
            }).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request) as response:
            published = json.loads(response.read())
        assert published["success"] is True
        assert published["build_source"] == "server_agent"
        assert published["visibility"] == "private"

        request = Request(
            f"{base}/api/research-publications/settings",
            data=json.dumps({
                "report_id": settings["reports"][0]["report_id"],
                "visibility": "authorized",
                "authorized_users": ["GTHT@Reader@2"],
            }).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request) as response:
            shared = json.loads(response.read())
        assert shared["success"] is True
        assert shared["settings"]["build_source"] == "server_agent"
        assert shared["settings"]["visibility"] == "authorized"

        request = Request(
            f"{base}/api/research-publications/settings",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urlopen(request) as response:
            settings = json.loads(response.read())
        assert settings["reports"][0]["sharing_state"] == "shared"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_report_settings_target_one_publication_branch(tmp_path: Path):
    state = manager.ManagerState(
        tmp_path, "python", data_root=tmp_path / "data",
        session_db_path=tmp_path / "manager.sqlite",
    )
    token = "branch-settings-token"
    state._sessions[state._token_hash(token)] = (
        PRINCIPAL, "user", float("inf"),
    )
    accounts = [
        {"username": "GTHT@Chief@1", "parent_username": "", "active": True},
        {"username": "GTHT@Boss@2", "parent_username": "GTHT@Chief@1", "active": True},
        {"username": PRINCIPAL, "parent_username": "GTHT@Boss@2", "active": True},
    ]
    state.control_store = SimpleNamespace(load_accounts=lambda: accounts)
    publications = []
    for branch in ("branch-a", "branch-b"):
        projection = {
            "schema_version": 2, "report_id": "report-branches",
            "title": branch, "language": "zh-Hans", "generation": 1,
            "components": [], "bindings": [], "assets": [],
            "local_resources": [], "related_objects": [], "attachments": [],
            "projection_hash": f"hash-{branch}",
        }
        synced = state.public_research.sync({
            "report_id": "report-branches",
            "publication_key": f"report-branches:branch:{branch}",
            "branch_ref": branch,
            "owner_ref": PRINCIPAL,
            "profile_ref": "maxa",
            "projection": projection,
        })
        state.public_research.configure(
            owner_ref=PRINCIPAL, report_id="report-branches",
            publication_key=f"report-branches:branch:{branch}",
            projection=None, visibility="private", auto_sync=True,
            relay_local_files=False, authorized_users=[],
        )
        publications.append(synced["publication_id"])
    research = state.research_catalog.create_research(
        owner_ref=PRINCIPAL, title="分支可见性研究",
    )
    state.research_catalog.register_report(
        research["research_id"], actor=PRINCIPAL,
        report_id="report-branches", title="分支报告",
        visibility="superiors",
    )
    manager.Handler.state = state
    server = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        request = Request(
            f"{base}/api/research-publications/settings",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urlopen(request) as response:
            initial_settings = json.loads(response.read())["reports"]
        assert {item["visibility"] for item in initial_settings} == {"superiors"}
        assert {item["research_id"] for item in initial_settings} == {
            research["research_id"],
        }

        request = Request(
            f"{base}/api/research-publications/settings",
            data=json.dumps({
                "publication_id": publications[1],
                "report_id": "report-branches",
                "research_id": research["research_id"],
                "visibility": "authorized",
                "auto_sync": False,
                "authorized_users": ["GTHT@Reader@2"],
            }).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request) as response:
            saved = json.loads(response.read())["settings"]
        assert saved["publication_id"] == publications[1]
        assert saved["branch_ref"] == "branch-b"
        assert saved["visibility"] == "authorized"
        assert saved["auto_sync"] is False
        catalog_report = state.research_catalog.list_reports(
            research["research_id"], viewer=PRINCIPAL,
        )[0]
        assert catalog_report["visibility"] == "authorized"
        first = state.public_research.owner_settings(publications[0], PRINCIPAL)
        assert first["visibility"] == "authorized"
        assert first["authorized_users"] == ["GTHT@Reader@2"]
        assert first["auto_sync"] is True

        request = Request(
            f"{base}/api/research/principals?relation=superiors",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urlopen(request) as response:
            principals = json.loads(response.read())["principals"]
        assert [item["principal_ref"] for item in principals] == [
            "GTHT@Boss@2", "GTHT@Chief@1",
        ]

        request = Request(
            f"{base}/api/research-publications/settings",
            data=json.dumps({
                "publication_id": publications[1],
                "report_id": "report-branches",
                "visibility": "superiors",
                "authorized_users": ["GTHT@Ignored@9"],
            }).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request) as response:
            superior_settings = json.loads(response.read())["settings"]
        assert superior_settings["visibility"] == "superiors"
        assert superior_settings["authorized_users"] == [
            "GTHT@Boss@2", "GTHT@Chief@1",
        ]
        assert {
            state.public_research.owner_settings(item, PRINCIPAL)["visibility"]
            for item in publications
        } == {"superiors"}
        assert state.research_catalog.list_reports(
            research["research_id"], viewer=PRINCIPAL,
        )[0]["visibility"] == "superiors"

        request = Request(
            f"{base}/api/research/{research['research_id']}/reports/report-branches",
            data=json.dumps({
                "visibility": "private", "authorized_users": [],
            }).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="PATCH",
        )
        with urlopen(request) as response:
            patched = json.loads(response.read())["report"]
        assert patched["visibility"] == "private"
        assert {
            state.public_research.owner_settings(item, PRINCIPAL)["visibility"]
            for item in publications
        } == {"private"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
