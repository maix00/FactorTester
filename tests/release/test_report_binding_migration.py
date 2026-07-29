from pathlib import Path

from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    initialize_tree,
    load_snapshot,
)
from tools.cli.release.research_reporting.maintenance.binding_targets import (
    rewrite_binding_target,
)


def test_rewrite_degraded_binding_as_typed_target(tmp_path: Path) -> None:
    package = tmp_path / "research" / "package-a"
    initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-main", title="研究报告",
    )
    add_component(
        package_root=package, branch_id="main",
        component_id="chapter-a", kind="chapter", title="假设登记",
        parent_id=None, body="", content=None, display_kind="",
        bindings=[{
            "binding_id": "claim-a", "kind": "claim",
            "target_ref": "legacy-link:abc", "label": "研究主张",
            "data": {
                "legacy_target_ref": "claim:SgCCS/value",
                "link_id": "claim",
            },
        }],
    )

    rewrite_binding_target(
        package_root=package, branch_id="main",
        component_id="chapter-a", binding_id="claim-a",
        expected_target_ref="legacy-link:abc",
        target_ref="claim:sgccs-value",
    )
    binding = load_snapshot(
        package_root=package, branch_id="main",
    )["bindings"][0]

    assert binding["target_ref"] == "claim:sgccs-value"
    assert binding["data"] == {"link_id": "claim"}
