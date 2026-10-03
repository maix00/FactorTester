from __future__ import annotations

from pathlib import Path

import pytest

from tools.cli.release.research_reporting.authoring.export import (
    export_branch_report,
)
from tools.cli.release.research_reporting.authoring.submission_gate import (
    begin_submission,
    fail_submission,
)
from tools.cli.release.research_reporting.authoring.submission_status import (
    load_reconciled_pending,
)
from tools.cli.release.research_reporting.authoring.tree_fork import (
    fork_report_tree,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    initialize_tree,
)
from tools.cli.release.research_reporting.authoring.tree_store import (
    load_head,
    write_head,
)
from tools.cli.release.research_reporting.maintenance.rich_text_lists import (
    migrate_rich_text,
)
from tools.cli.release.research_reporting.maintenance.root_hierarchy import (
    migrate_single_chapter_root,
)


def _blocked_tree(tmp_path: Path) -> tuple[Path, dict]:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-wp", title="研究报告",
    )
    submission = begin_submission(
        package_root=package, branch_id="main", requested_sequence=None,
        logical_identity={
            "operation": "add",
            "components": [{"component_id": "chapter"}],
        },
        payload={"body": r"broken \("},
    )
    fail_submission(
        package_root=package, branch_id="main", submission=submission,
        diagnostics=[{"code": "report.math.invalid"}],
    )
    return package, created


@pytest.mark.parametrize(
    "operation",
    [
        lambda package: migrate_single_chapter_root(
            package_root=package, branch_id="main",
        ),
        lambda package: migrate_rich_text(
            package_root=package, branch_id="main",
        ),
    ],
)
def test_pending_blocks_maintenance_publishers(
    tmp_path: Path, operation,
) -> None:
    package, _created = _blocked_tree(tmp_path)
    with pytest.raises(ValueError, match="submission_sequence 1"):
        operation(package)


def test_pending_source_cannot_be_forked(tmp_path: Path) -> None:
    package, _created = _blocked_tree(tmp_path)
    with pytest.raises(ValueError, match="submission_sequence 1"):
        fork_report_tree(
            package_root=package, source_branch_id="main",
            target_branch_id="fork", target_report_id="report-wp",
        )
    assert not (
        package / "branches" / "fork" / "authoring" / "HEAD.json"
    ).exists()


def test_pending_cannot_render_or_commit_old_head(tmp_path: Path) -> None:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-wp", title="研究报告",
    )
    add_component(
        package_root=package, branch_id="main", component_id="chapter",
        kind="chapter", title="假设登记", parent_id=None, body="",
        content=None, display_kind="",
    )
    first = export_branch_report(
        package_root=package, report_workspace_id="report-wp",
        branch_id="main", commit=False,
    )
    before = first["path"].read_bytes()
    submission = begin_submission(
        package_root=package, branch_id="main", requested_sequence=None,
        logical_identity={"operation": "add", "components": [{"component_id": "x"}]},
        payload={"body": "invalid"},
    )
    fail_submission(
        package_root=package, branch_id="main", submission=submission,
        diagnostics=[{"code": "blocked"}],
    )

    with pytest.raises(ValueError, match="submission_sequence 2"):
        export_branch_report(
            package_root=package, report_workspace_id="report-wp",
            branch_id="main", commit=True,
        )
    assert first["path"].read_bytes() == before


def test_status_read_reconciles_pending_after_durable_head(tmp_path: Path) -> None:
    package, created = _blocked_tree(tmp_path)
    head = load_head(created["paths"])
    write_head(created["paths"], {
        **head, "generation": 1, "locator_generation": 0,
    })

    pending = load_reconciled_pending(
        package_root=package, branch_id="main",
    )
    assert pending is not None
    assert pending["phase"] == "published"
    assert created["paths"]["pending_submission"].exists()
