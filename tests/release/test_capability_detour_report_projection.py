from tools.cli.release.research_reporting.authoring.tree_detours import (
    ensure_capability_detour_special,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    apply_batch,
    ensure_node_chapter,
    initialize_tree,
    load_snapshot,
)
from tools.cli.release.research_obligations.transition_report import (
    target_container_operations,
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


def test_transition_receipt_preserves_detour_nested_in_authored_special(
    tmp_path,
):
    initialize_tree(
        package_root=tmp_path,
        branch_id="branch",
        report_id="report",
        title="研究报告",
    )
    chapter = ensure_node_chapter(
        package_root=tmp_path,
        branch_id="branch",
        node_id="hypothesis_preregistration",
        title="假设预注册",
    )
    add_component(
        package_root=tmp_path,
        branch_id="branch",
        component_id="grill",
        kind="special",
        title="方向门控 Grill",
        parent_id=chapter["component_id"],
        body="",
        content={},
        display_kind="grill_resolution",
    )
    add_component(
        package_root=tmp_path,
        branch_id="branch",
        component_id="legacy-detour",
        kind="special",
        title="能力缺口修复：临时因子绑定",
        parent_id="grill",
        body="保留原位置",
        content={"legacy": True},
        display_kind="capability_detour",
        bindings=[{
            "binding_id": "legacy-detour-binding",
            "kind": "graph_reference",
            "target_ref": "capability-detour:origin",
            "label": "能力修复过程",
            "data": {"role": "capability_detour"},
        }],
    )

    operations, _ = target_container_operations(
        package_root=tmp_path,
        branch_id="branch",
        container={
            "kind": "special",
            "anchor_node": "hypothesis_preregistration",
            "current_node": "capability_gap",
            "detour": {
                "episode_id": "capability-detour:origin",
                "origin_trace_id": "origin",
                "resume_node": "hypothesis_preregistration",
                "status": "retained",
                "latest_trace_id": "transition-2",
            },
        },
    )
    apply_batch(
        package_root=tmp_path,
        branch_id="branch",
        operations=operations,
    )
    saved = load_snapshot(package_root=tmp_path, branch_id="branch")
    detour = next(
        item for item in saved["components"]
        if item["component_id"] == "legacy-detour"
    )
    assert detour["parent_id"] == "grill"
    assert detour["title"] == "能力缺口修复：临时因子绑定"
    assert detour["content"]["legacy"] is True
