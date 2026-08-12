from __future__ import annotations

from types import SimpleNamespace

import pytest

from tools.cli.commands.research_report_submission import begin_batch_submission
from tools.cli.commands.research_report_submission_errors import (
    SequencedSubmissionError,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    initialize_tree,
)


def _scope(tmp_path) -> SimpleNamespace:
    package = tmp_path / "research" / "wp"
    initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-wp", title="研究报告",
    )
    for component_id in ("chapter-a", "chapter-b"):
        add_component(
            package_root=package, branch_id="main",
            component_id=component_id, kind="chapter",
            title=component_id, parent_id=None, body="",
            content=None, display_kind="",
        )
    add_component(
        package_root=package, branch_id="main",
        component_id="entry", kind="entry", title="条目",
        parent_id="chapter-a", body="", content=None, display_kind="",
    )
    return SimpleNamespace(package_root=package, branch_id="main")


def _move() -> dict[str, object]:
    return {
        "op": "move", "component_id": "entry",
        "parent_id": "chapter-b", "after_component_id": None,
    }


def test_move_raw_bindings_are_rejected_and_corrected_in_same_sequence(
    tmp_path,
) -> None:
    scope = _scope(tmp_path)
    with pytest.raises(SequencedSubmissionError) as caught:
        begin_batch_submission(
            scope=scope, requested_sequence=None, as_json=False,
            operations=[{**_move(), "bindings": []}],
        )

    assert caught.value.sequence == 4
    assert caught.value.diagnostics[0]["code"] == (
        "report.binding.agent_forbidden"
    )
    resumed, enriched = begin_batch_submission(
        scope=scope, requested_sequence=4, as_json=False,
        operations=[_move()],
    )
    assert resumed.sequence == 4
    assert enriched == [_move()]
