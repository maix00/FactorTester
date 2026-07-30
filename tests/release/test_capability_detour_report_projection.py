from tools.cli.release.research_reporting.authoring.tree_detours import (
    ensure_capability_detour_special,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    ensure_node_chapter,
    initialize_tree,
    load_snapshot,
)


def test_current_episode_status_does_not_rewrite_existing_trace(tmp_path):
    package = tmp_path / "research" / "package"
    initialize_tree(
        package_root=package,
        branch_id="branch",
        report_id="report",
        title="研究报告",
    )
    chapter = ensure_node_chapter(
        package_root=package,
        branch_id="branch",
        node_id="hypothesis_preregistration",
        title="假设预注册",
    )
    detour = {
        "episode_id": "capability-detour:episode",
        "origin_trace_id": "origin",
        "resume_node": "hypothesis_preregistration",
        "status": "retained",
    }
    first = ensure_capability_detour_special(
        package_root=package,
        branch_id="branch",
        parent_id=chapter["component_id"],
        detour=detour,
        current_node="capability_resolution",
        latest_trace_id="transition-1",
    )

    ensure_capability_detour_special(
        package_root=package,
        branch_id="branch",
        parent_id=chapter["component_id"],
        detour={**detour, "status": "pending"},
        current_node="capability_resolution",
        latest_trace_id="transition-1",
        component_id_hint=first["component_id"],
    )

    snapshot = load_snapshot(
        package_root=package,
        branch_id="branch",
    )
    special = next(
        item for item in snapshot["components"]
        if item["component_id"] == first["component_id"]
    )
    assert special["content"]["status"] == "pending"
    assert special["content"]["transitions"] == [{
        "trace_ref": "trace:transition-1",
        "status": "retained",
        "node_id": "capability_resolution",
    }]
