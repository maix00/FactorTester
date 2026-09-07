from pathlib import Path

import pytest

from server.manager.services.agent_workspace import ensure_server_profile_workspace
from server.manager.services.server_research import ServerResearchService
from server.manager.storage.profile_runtime_store import ProfileRuntimeStore
from tools.cli.release.research_reporting.authoring.tree_fork import fork_report_tree
from tools.cli.release.research_reporting.public_research.library import (
    PublicResearchLibrary,
)
from tools.cli.release.research_reporting.workspace import initialize_work_package

PRINCIPAL = "GTHT@MaxJJW@392452984564"


def _service(tmp_path: Path) -> tuple[ServerResearchService, str]:
    data_root = tmp_path / "data"
    profile_id = "profile-main"
    workspace = ensure_server_profile_workspace(data_root, PRINCIPAL, profile_id)
    runtime_store = ProfileRuntimeStore(tmp_path / "manager.sqlite")
    runtime_store.bind(
        PRINCIPAL,
        profile_id,
        runtime_kind="server",
        executor_id="public-1",
        workspace_relpath="users/profile/profiles/profile-main",
    )
    initialize_work_package(
        workspace_root=workspace,
        work_package_id="report-one",
        branch_id="main",
        workspace_id="profile-main",
        title="服务器 Agent 报告",
        branch_ref="graph-branch:report-one:main",
    )
    return ServerResearchService(data_root, runtime_store, server_id="public-1"), profile_id


def test_server_agent_report_is_listed_and_read_from_canonical_workspace(tmp_path):
    service, profile_id = _service(tmp_path)

    rows = service.list_owner(PRINCIPAL)

    assert len(rows) == 1
    row = rows[0]
    assert row["server_ref"] == f"{profile_id}:report-one:main"
    assert row["build_source"] == "server_agent"
    assert row["sharing_state"] == "not_shared"
    assert row["is_shared"] is False

    index = service.index(PRINCIPAL, row["server_ref"])
    assert index["profile_id"] == profile_id
    assert index["work_package_id"] == "report-one"
    assert index["branch_id"] == "main"
    assert index["title"] == "服务器 Agent 报告"
    assert index["access"]["build_source"] == "server_agent"
    assert index["access"]["sharing_state"] == "not_shared"


def test_server_report_reader_lists_sibling_branches_in_one_work_package(tmp_path):
    service, profile_id = _service(tmp_path)
    row = service.list_owner(PRINCIPAL)[0]
    package_root = service._location(PRINCIPAL, row["server_ref"])["package_root"]
    fork_report_tree(
        package_root=package_root,
        source_branch_id="main",
        target_branch_id="alternative",
        target_report_id=row["report_id"],
    )

    index = service.index(PRINCIPAL, row["server_ref"])

    assert [item["branch_ref"] for item in index["branches"]] == [
        "alternative", "main",
    ]
    assert sum(bool(item["selected"]) for item in index["branches"]) == 1
    assert index["branches"][1]["publication_id"] == (
        f"server:{profile_id}:report-one:main"
    )


def test_server_agent_report_can_be_explicitly_shared_with_provenance(tmp_path):
    service, _profile_id = _service(tmp_path)
    row = service.list_owner(PRINCIPAL)[0]
    library = PublicResearchLibrary(tmp_path / "public-research", storage_server_id="public-1")

    result = service.publish(
        PRINCIPAL,
        row["server_ref"],
        public_research=library,
        visibility="public",
    )

    assert result["build_source"] == "server_agent"
    assert result["sharing_state"] == "shared"
    listed = library.list_visible(None)[0]
    assert listed["build_source"] == "server_agent"
    assert listed["sharing_state"] == "shared"
    assert listed["is_shared"] is True

    with pytest.raises(PermissionError, match="construction source"):
        library.sync({
            "report_id": listed["report_id"],
            "owner_ref": PRINCIPAL,
            "build_source": "client",
            "projection": service.projection(PRINCIPAL, row["server_ref"]),
        })


def test_server_research_reference_is_owner_and_shape_scoped(tmp_path):
    service, _profile_id = _service(tmp_path)

    with pytest.raises(PermissionError):
        service.projection("other-owner", "profile-main:report-one:main")
    with pytest.raises(ValueError, match="reference is invalid"):
        service.projection(PRINCIPAL, "profile-main:report-one:main:extra")
