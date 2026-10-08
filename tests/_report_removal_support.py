from __future__ import annotations

from tools.cli.commands import research_report_component_removal
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    load_snapshot,
)
from tools.cli.release.research_reporting.workspace import initialize_report_workspace


def scope(tmp_path):
    client_root, workspace = tmp_path / "client", tmp_path / "workspace"
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141", workspace_root=workspace,
    )
    LocalProfileStore(client_root).save(profile)
    initialized = initialize_report_workspace(
        workspace_root=workspace, report_workspace_id="wp", branch_id="main",
        report_id="report-1", workspace_id="one", title="报告",
        branch_ref="report-branch:main",
    )
    add_component(
        package_root=initialized["package_root"], branch_id="main",
        component_id="chapter", kind="chapter", title="假设登记",
        parent_id=None, body="", content=None, display_kind="",
    )
    return client_root, initialized["package_root"], "chapter"


def patch_scope(monkeypatch, client_root):
    monkeypatch.setattr(
        research_report_component_removal,
        "load_profile_root", lambda _path: client_root,
    )


def args():
    return [
        "--profile", "maxa", "--report-workspace-id", "wp",
        "--branch-id", "main",
    ]


def add(
    package, component_id, kind, parent_id, display_kind="", bindings=None,
):
    add_component(
        package_root=package, branch_id="main",
        component_id=component_id, kind=kind, title=component_id,
        parent_id=parent_id, body="正文", content=None,
        display_kind=display_kind, bindings=bindings,
    )


def component_ids(package):
    return {
        item["component_id"]
        for item in load_snapshot(
            package_root=package, branch_id="main",
        )["components"]
    }
