"""Cross-principal branch read for research report collaboration.

Group A (owner/editor) author branches in their own profile workspaces.  A
reader (group B) can read them.  Only local ``server_agent`` branches are
resolved here; a branch from another source (client / publication / remote
server) is honestly reported as not-local rather than misreading a workspace.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from server.manager.services.agent_workspace import ensure_server_profile_workspace
from server.manager.services.server_research import ServerResearchService
from server.manager.storage.profile_runtime_store import ProfileRuntimeStore
from tools.cli.release.research_reporting.authoring.tree_assets import append_asset
from tools.cli.release.research_reporting.authoring.tree_fork import (
    inherit_report_tree_across_packages,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
)
from tools.cli.release.research_reporting.authoring.tree_paths import (
    report_tree_paths,
)
from tools.cli.release.research_reporting.workspace import initialize_work_package

OWNER = "GTHT@owner@1"
EDITOR_A = "GTHT@editorA@2"
READER = "GTHT@reader@3"


@pytest.fixture
def png_bytes() -> bytes:
    # Minimal valid 1x1 transparent PNG.
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42m"
        "Nk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )


def _bind(store: ProfileRuntimeStore, principal: str, profile_id: str) -> None:
    store.bind(
        principal, profile_id,
        runtime_kind="server", executor_id="public-1",
        workspace_relpath=f"users/{principal}/profiles/{profile_id}",
    )


def _service(tmp_path: Path) -> ServerResearchService:
    data_root = tmp_path / "data"
    store = ProfileRuntimeStore(tmp_path / "manager.sqlite")
    for principal, pid in [
        (OWNER, "profile-owner"),
        (EDITOR_A, "profile-editor"),
        (READER, "profile-reader"),
    ]:
        ensure_server_profile_workspace(data_root, principal, pid)
        _bind(store, principal, pid)
    return ServerResearchService(data_root, store, server_id="public-1")


def test_branch_read_resolves_against_creator_workspace(tmp_path):
    service = _service(tmp_path)
    owner_ws = ensure_server_profile_workspace(
        tmp_path / "data", OWNER, "profile-owner",
    )
    initialize_work_package(
        workspace_root=owner_ws, work_package_id="report-one",
        branch_id="main", workspace_id="profile-owner",
        title="协作报告", branch_ref="graph-branch:report-one:main",
    )
    editor_ws = ensure_server_profile_workspace(
        tmp_path / "data", EDITOR_A, "profile-editor",
    )
    editor_pkg = editor_ws / "research" / "report-one"
    inherit_report_tree_across_packages(
        source_package_root=owner_ws / "research" / "report-one",
        target_package_root=editor_pkg,
        source_branch_id="main",
        target_branch_id="editor-main",
        target_report_id="report-one-editor",
    )
    add_component(
        package_root=editor_pkg, branch_id="editor-main",
        component_id="editor-chapter", kind="chapter", title="编辑章节",
        parent_id=None, body="", content=None, display_kind="",
    )

    # Reader reads the EDITOR's branch, resolved against EDITOR's workspace.
    value = service.read_branch(
        READER,
        target_ref=EDITOR_A,
        profile_id="profile-editor",
        package_id="report-one",
        branch_id="editor-main",
    )
    assert value["available"] is True
    assert value["branch_id"] == "editor-main"
    assert value["profile_id"] == "profile-editor"
    assert value["build_source"] == "server_agent"


def test_read_branch_denied_for_invalid_reference(tmp_path):
    service = _service(tmp_path)
    with pytest.raises(ValueError, match="reference is invalid"):
        service.read_branch(
            READER,
            target_ref=EDITOR_A,
            profile_id="bad/../path",
            package_id="report-one",
            branch_id="main",
        )


def test_read_branch_reports_non_local_source_honestly(tmp_path):
    service = _service(tmp_path)
    value = service.read_branch(
        READER,
        target_ref=EDITOR_A,
        profile_id="profile-editor",
        package_id="report-one",
        branch_id="editor-main",
        build_source="client",
    )
    assert value["available"] is False
    assert value["reason"] == "source-not-local"
    assert value["build_source"] == "client"


def test_reader_reads_foreign_branch_asset(png_bytes: bytes, tmp_path):
    service = _service(tmp_path)
    owner_ws = ensure_server_profile_workspace(
        tmp_path / "data", OWNER, "profile-owner",
    )
    initialize_work_package(
        workspace_root=owner_ws, work_package_id="report-one",
        branch_id="main", workspace_id="profile-owner",
        title="协作报告", branch_ref="graph-branch:report-one:main",
    )
    editor_ws = ensure_server_profile_workspace(
        tmp_path / "data", EDITOR_A, "profile-editor",
    )
    editor_pkg = editor_ws / "research" / "report-one"
    inherit_report_tree_across_packages(
        source_package_root=owner_ws / "research" / "report-one",
        target_package_root=editor_pkg,
        source_branch_id="main",
        target_branch_id="editor-main",
        target_report_id="report-one-editor",
    )
    # Write an asset byte + register it on the editor branch.
    paths = report_tree_paths(editor_pkg, "editor-main")
    asset_dir = paths["root"] / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / "diagram.png").write_bytes(png_bytes)
    import hashlib

    head = paths["head"]
    # Load current head, append asset, write back.
    from tools.cli.release.research_reporting.authoring.tree_store import (
        load_head, write_head,
    )

    head_value = load_head(paths)
    head_value = append_asset(head_value, {
        "asset_ref": "asset:diagram.png",
        "media_type": "image/png",
        "filename": "diagram.png",
        "caption": "协作图",
        "alt_text": "协作图",
        "content_hash": hashlib.sha256(png_bytes).hexdigest(),
    })
    write_head(paths, head_value)

    asset_id = hashlib.sha256(
        "asset:diagram.png".encode("utf-8"),
    ).hexdigest()[:24]
    # Reader fetches the EDITOR's asset, resolved against EDITOR's workspace.
    raw, media_type, filename = service.asset(
        READER,
        "profile-editor:report-one:editor-main",
        asset_id,
        target_ref=EDITOR_A,
    )
    assert raw == png_bytes
    assert media_type == "image/png"
    assert filename == "diagram.png"

