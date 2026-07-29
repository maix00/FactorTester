from __future__ import annotations

from pathlib import Path

from tools.cli.commands.research_report_submission_identity import batch_identity
from tools.cli.release.research_reporting.authoring.submission_gate import (
    begin_submission,
    fail_submission,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    apply_batch,
    initialize_tree,
)


def test_missing_batch_component_id_can_be_corrected_in_same_slot(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-wp", title="研究报告",
    )
    invalid = [{
        "op": "add", "kind": "chapter", "title": "结论",
        "body": "", "content": None, "display_kind": "",
    }]
    first = begin_submission(
        package_root=package, branch_id="main", requested_sequence=None,
        logical_identity=batch_identity(invalid), payload=invalid,
    )
    fail_submission(
        package_root=package, branch_id="main", submission=first,
        diagnostics=[{"code": "component_id.invalid"}],
    )
    corrected = [{**invalid[0], "component_id": "finding"}]
    resumed = begin_submission(
        package_root=package, branch_id="main", requested_sequence=1,
        logical_identity=batch_identity(corrected), payload=corrected,
    )

    saved = apply_batch(
        package_root=package, branch_id="main",
        operations=corrected, submission=resumed,
    )
    assert saved["head"]["generation"] == 1
