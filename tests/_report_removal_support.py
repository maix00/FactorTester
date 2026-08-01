from __future__ import annotations

from tools.cli.commands import (
    research_report_component_removal,
    research_report_graph_guard,
)
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    ensure_node_chapter,
    load_snapshot,
)
from tools.cli.release.research_reporting.workspace import initialize_work_package


def scope(tmp_path):
    client_root, workspace = tmp_path / "client", tmp_path / "workspace"
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141", workspace_root=workspace,
    )
    profile["research_records"] = [{
        "record_id": "wp", "title": "报告", "status": "pending",
        "scope": {}, "factor_family_versions": [],
        "agent_id": "research-maxa", "created_at": 1, "updated_at": 1,
        "workspace_ref": "workspace:one", "run_ref": "",
        "graph_instance_ref": "work-package:wp",
        "graph_branch_ref": "graph-branch:instance:main",
        "checkpoint_ref": "", "evidence_refs": [], "timeline_refs": [],
        "artifacts": [], "provenance": {"kind": "owned_research"},
    }]
    LocalProfileStore(client_root).save(profile)
    initialized = initialize_work_package(
        workspace_root=workspace, work_package_id="wp", branch_id="main",
        workspace_id="one", title="报告",
        branch_ref="graph-branch:instance:main",
    )
    chapter = ensure_node_chapter(
        package_root=initialized["package_root"], branch_id="main",
        node_id="hypothesis_preregistration", title="假设登记",
    )
    return client_root, initialized["package_root"], chapter["component_id"]


def patch_scope(monkeypatch, client_root):
    monkeypatch.setattr(
        research_report_component_removal,
        "load_profile_root", lambda _path: client_root,
    )
    monkeypatch.setattr(
        research_report_graph_guard, "fetch_graph_node_packet",
        lambda _scope: {
            "current_node": "hypothesis_preregistration",
            "report_container": {
                "kind": "chapter",
                "anchor_node": "hypothesis_preregistration",
            },
        },
    )


def args():
    return [
        "--profile", "maxa", "--work-package-id", "wp",
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
