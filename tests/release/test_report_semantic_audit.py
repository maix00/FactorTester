from pathlib import Path

from tools.cli.release.research_reporting.authoring.export import (
    export_branch_report,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    initialize_tree,
)
from tools.cli.release.research_reporting.maintenance.semantic_audit import (
    audit_branch_report,
)


def test_audit_records_each_rich_component_and_rendered_export(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "package-a"
    initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-main", title="研究报告",
    )
    _add(package, "chapter", "chapter", None, "假设登记")
    _add(
        package, "entry", "entry", "chapter", "正文",
        body="信号为 `close`，定义成 \\(r_t=P_t/P_{t-1}-1\\)",
    )
    _add(
        package, "code", "code", "chapter", "实现",
        content={"language": "python", "code": "signal = close.pct_change()"},
    )
    _add(
        package, "math", "math", "chapter", "公式",
        content={"latex": r"r_t=P_t/P_{t-1}-1", "fallback": "收益率"},
    )
    _add(
        package, "table", "table", "chapter", "结果",
        content={"columns": ["指标", "值"], "rows": [["IC", r"\(0.03\)"]]},
        bindings=[{
            "binding_id": "evidence-a", "kind": "evidence",
            "target_ref": "evidence:a", "label": "样本证据", "data": {},
        }],
    )
    export_branch_report(
        package_root=package, report_workspace_id="package-a",
        branch_id="main", commit=False,
    )

    audit = audit_branch_report(package_root=package, branch_id="main")

    assert audit["valid"] is True
    assert audit["component_count"] == 5
    assert audit["component_kinds"] == {
        "chapter": 1, "code": 1, "entry": 1, "math": 1, "table": 1,
    }
    assert audit["rich_features"] == {
        "inline_code": 1, "inline_math": 2, "typed_code": 1,
        "typed_math": 1, "typed_table": 1,
    }
    assert audit["report_markdown_matches"] is True
    assert len(audit["items"]) == 5
    assert audit["items"][-1]["binding_ids"] == ["evidence-a"]


def test_audit_rejects_stale_markdown_export(tmp_path: Path) -> None:
    package = tmp_path / "research" / "package-a"
    initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-main", title="研究报告",
    )
    _add(package, "chapter", "chapter", None, "假设登记")
    report = package / "branches" / "main" / "REPORT.md"
    report.write_text("# stale\n", encoding="utf-8")

    audit = audit_branch_report(package_root=package, branch_id="main")

    assert audit["valid"] is False
    assert audit["errors"] == [
        "REPORT.md does not match the current report tree",
    ]


def _add(
    package: Path, component_id: str, kind: str, parent_id: str | None,
    title: str, *, body: str = "", content=None, bindings=None,
) -> None:
    add_component(
        package_root=package, branch_id="main", component_id=component_id,
        kind=kind, title=title, parent_id=parent_id, body=body,
        content=content, display_kind="", bindings=bindings,
    )
