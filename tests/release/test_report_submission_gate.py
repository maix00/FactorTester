from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools.cli.release.research_reporting.authoring.submission_gate import (
    begin_submission,
    fail_submission,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    initialize_tree,
)


def _tree(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package,
        branch_id="main",
        report_id="report-wp",
        title="研究报告",
    )
    return package, created


def _identity(component_id: str = "finding") -> dict[str, object]:
    return {
        "operation": "add",
        "components": [{
            "component_id": component_id,
            "kind": "chapter",
            "parent_id": None,
        }],
    }


def test_failed_submission_reserves_next_generation_without_moving_head(
    tmp_path: Path,
) -> None:
    package, created = _tree(tmp_path)
    before = created["paths"]["head"].read_bytes()

    submission = begin_submission(
        package_root=package,
        branch_id="main",
        requested_sequence=None,
        logical_identity=_identity(),
        payload={"body": r"broken \("},
    )
    fail_submission(
        package_root=package,
        branch_id="main",
        submission=submission,
        diagnostics=[{"code": "report.math.invalid"}],
    )

    assert submission.sequence == 1
    assert created["paths"]["head"].read_bytes() == before
    pending = json.loads(
        created["paths"]["pending_submission"].read_text(encoding="utf-8")
    )
    assert pending["submission_sequence"] == 1
    assert pending["base_generation"] == 0
    assert pending["logical_identity"] == _identity()
    assert pending["diagnostics"] == [{"code": "report.math.invalid"}]


def test_pending_submission_blocks_unrelated_report_mutation(tmp_path: Path) -> None:
    package, _created = _tree(tmp_path)
    submission = begin_submission(
        package_root=package,
        branch_id="main",
        requested_sequence=None,
        logical_identity=_identity(),
        payload={"body": "first"},
    )
    fail_submission(
        package_root=package,
        branch_id="main",
        submission=submission,
        diagnostics=[{"code": "blocked"}],
    )

    with pytest.raises(ValueError, match="submission_sequence 1"):
        add_component(
            package_root=package,
            branch_id="main",
            component_id="other",
            kind="chapter",
            title="其他",
            parent_id=None,
            body="",
            content=None,
            display_kind="",
        )
