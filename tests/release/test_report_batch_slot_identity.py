from __future__ import annotations

from types import SimpleNamespace

from tools.cli.commands.research_report_submission import begin_batch_submission
from tools.cli.release.research_reporting.authoring.submission_gate import (
    fail_submission,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    initialize_tree,
)


def test_invalid_component_operation_can_be_corrected_in_same_slot(
    tmp_path,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-wp", title="研究报告",
    )
    add_component(
        package_root=package, branch_id="main",
        component_id="chapter", kind="chapter", title="旧章节",
        parent_id=None, body="", content=None, display_kind="",
    )
    scope = SimpleNamespace(package_root=package, branch_id="main")
    failed, _operations = begin_batch_submission(
        scope=scope, requested_sequence=None, as_json=False,
        operations=[{"op": "invalid", "component_id": "chapter"}],
    )
    fail_submission(
        package_root=package, branch_id="main", submission=failed,
        diagnostics=[{"code": "report.submission.invalid"}],
    )

    corrected, enriched = begin_batch_submission(
        scope=scope, requested_sequence=2, as_json=False,
        operations=[{
            "op": "replace", "component_id": "chapter",
            "title": "新章节", "body": "正文", "content": None,
            "display_kind": "",
        }],
    )

    assert corrected.sequence == 2
    assert enriched[0]["kind"] == "chapter"
