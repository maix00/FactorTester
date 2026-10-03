from pathlib import Path

from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    initialize_tree,
    load_snapshot,
)
from tools.cli.release.research_reporting.maintenance.lineage import (
    prepend_branch_snapshot,
)


def test_lineage_repair_preserves_all_rich_component_types(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "package-a"
    _initialize(package, "ancestor")
    _initialize(package, "descendant")
    binding = {
        "binding_id": "evidence-a", "kind": "evidence",
        "target_ref": "evidence:a", "label": "样本证据", "data": {},
    }
    _add(package, "ancestor", "chapter-a", "chapter", None, "假设登记")
    _add(
        package, "ancestor", "code-a", "code", "chapter-a", "公式实现",
        content={"language": "python", "code": "signal = close / open - 1"},
    )
    _add(
        package, "ancestor", "math-a", "math", "chapter-a", "因子公式",
        content={"latex": r"r_t=P_t/P_{t-1}-1", "fallback": "收益率"},
    )
    _add(
        package, "ancestor", "table-a", "table", "chapter-a", "结果",
        content={"columns": ["指标", "值"], "rows": [["IC", r"\(0.03\)"]]},
        bindings=[binding],
    )
    _add(package, "descendant", "chapter-b", "chapter", None, "结果审计")

    result = prepend_branch_snapshot(
        package_root=package,
        source_branch_id="ancestor",
        target_branch_id="descendant",
    )
    snapshot = result["snapshot"]

    assert [item["component_id"] for item in snapshot["components"]] == [
        "chapter-a", "code-a", "math-a", "table-a", "chapter-b",
    ]
    assert snapshot["components"][1]["content"]["language"] == "python"
    assert snapshot["components"][2]["content"]["latex"].startswith("r_t")
    assert snapshot["components"][3]["content"]["rows"] == [["IC", r"\(0.03\)"]]
    assert snapshot["bindings"][0]["target_ref"] == "evidence:a"
    generation = snapshot["head"]["generation"]
    assert prepend_branch_snapshot(
        package_root=package,
        source_branch_id="ancestor",
        target_branch_id="descendant",
    )["added_component_ids"] == []
    assert load_snapshot(
        package_root=package, branch_id="descendant",
    )["head"]["generation"] == generation


def test_lineage_repair_fills_binding_missing_from_matching_component(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "package-a"
    for branch in ("ancestor", "descendant"):
        _initialize(package, branch)
    binding = {
        "binding_id": "evidence-a", "kind": "evidence",
        "target_ref": "evidence:a", "label": "样本证据", "data": {},
    }
    _add(
        package, "ancestor", "chapter-a", "chapter", None, "假设登记",
        bindings=[binding],
    )
    _add(
        package, "descendant", "chapter-a", "chapter", None, "假设登记",
    )

    result = prepend_branch_snapshot(
        package_root=package,
        source_branch_id="ancestor",
        target_branch_id="descendant",
    )

    assert result["added_component_ids"] == []
    assert result["added_binding_ids"] == ["evidence-a"]
    assert result["snapshot"]["bindings"][0]["target_ref"] == "evidence:a"


def _initialize(package: Path, branch_id: str) -> None:
    initialize_tree(
        package_root=package, branch_id=branch_id,
        report_id=f"report-{branch_id}", title="研究报告",
    )


def _add(
    package: Path, branch: str, component_id: str, kind: str,
    parent_id: str | None, title: str, *, content=None, bindings=None,
) -> None:
    add_component(
        package_root=package, branch_id=branch, component_id=component_id,
        kind=kind, title=title, parent_id=parent_id, body="",
        content=content, display_kind="", bindings=bindings,
    )
