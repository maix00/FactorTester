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


def _identity() -> dict[str, object]:
    return {
        "operation": "add",
        "components": [{"component_id": "finding"}],
    }


def test_newer_retry_supersedes_an_older_same_sequence_lease(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package,
        branch_id="main",
        report_id="report-wp",
        title="研究报告",
    )
    first = begin_submission(
        package_root=package,
        branch_id="main",
        requested_sequence=None,
        logical_identity=_identity(),
        payload={"body": "broken"},
    )
    fail_submission(
        package_root=package,
        branch_id="main",
        submission=first,
        diagnostics=[{"code": "blocked"}],
    )
    stale = begin_submission(
        package_root=package,
        branch_id="main",
        requested_sequence=1,
        logical_identity=_identity(),
        payload={"body": "older correction"},
    )
    current = begin_submission(
        package_root=package,
        branch_id="main",
        requested_sequence=1,
        logical_identity=_identity(),
        payload={"body": "newer correction"},
    )

    with pytest.raises(ValueError, match="superseded by a newer retry"):
        add_component(
            package_root=package,
            branch_id="main",
            component_id="finding",
            kind="chapter",
            title="结论",
            parent_id=None,
            body="older correction",
            content=None,
            display_kind="",
            submission=stale,
        )
    assert json.loads(
        created["paths"]["head"].read_text(encoding="utf-8")
    )["generation"] == 0

    saved = add_component(
        package_root=package,
        branch_id="main",
        component_id="finding",
        kind="chapter",
        title="结论",
        parent_id=None,
        body="newer correction",
        content=None,
        display_kind="",
        submission=current,
    )
    assert saved["head"]["generation"] == 1
