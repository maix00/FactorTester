from __future__ import annotations

from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    ensure_node_chapter,
    initialize_tree,
)


def test_ensure_reuses_legacy_chapter_bound_to_same_graph_node(tmp_path):
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="branch", report_id="report",
        title="动量因子研究",
    )
    add_component(
        package_root=package, branch_id="branch",
        component_id="chapter-legacy", kind="chapter", title="假设登记",
        parent_id=None, body="", content=None, display_kind="",
        bindings=[{
            "binding_id": "legacy-hypothesis", "kind": "graph_reference",
            "target_ref": "node:hypothesis_preregistration",
            "label": "假设登记",
            "data": {
                "role": "report_chapter",
                "chapter_ref": "node:hypothesis_preregistration",
            },
        }],
        include_snapshot=False,
    )

    result = ensure_node_chapter(
        package_root=package, branch_id="branch",
        node_id="hypothesis_preregistration", title="假设登记",
    )

    assert result["changed"] is False
    assert result["component_id"] == "chapter-legacy"
    assert result["head"]["generation"] == 1
