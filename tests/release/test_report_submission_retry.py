from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.cli.release.research_reporting.authoring import submission_finalize
from tools.cli.release.research_reporting.authoring.submission_gate import (
    begin_submission,
    fail_submission,
    reconcile_submission,
)
from tools.cli.release.research_reporting.authoring.submission_finalize import (
    finalize_published_submission,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    initialize_tree,
)
from tools.cli.release.research_reporting.authoring.tree_store import write_head


def _tree(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    package = tmp_path / "research" / "wp"
    created = initialize_tree(
        package_root=package, branch_id="main",
        report_id="report-wp", title="研究报告",
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


def test_only_same_sequence_and_logical_submission_can_correct_pending(
    tmp_path: Path,
) -> None:
    package, created = _tree(tmp_path)
    first = begin_submission(
        package_root=package, branch_id="main", requested_sequence=None,
        logical_identity=_identity(), payload={"body": "broken"},
    )
    fail_submission(
        package_root=package, branch_id="main", submission=first,
        diagnostics=[{"code": "blocked"}],
    )
    with pytest.raises(ValueError, match="--submission-sequence 1"):
        begin_submission(
            package_root=package, branch_id="main", requested_sequence=None,
            logical_identity=_identity(), payload={"body": "corrected"},
        )
    with pytest.raises(ValueError, match="different logical submission"):
        begin_submission(
            package_root=package, branch_id="main", requested_sequence=1,
            logical_identity=_identity("different"), payload={"body": "new"},
        )

    correction = begin_submission(
        package_root=package, branch_id="main", requested_sequence=1,
        logical_identity=_identity(), payload={"body": "corrected"},
    )
    pending = json.loads(
        created["paths"]["pending_submission"].read_text(encoding="utf-8")
    )
    assert pending["diagnostics"] == [{"code": "blocked"}]
    saved = add_component(
        package_root=package, branch_id="main", component_id="finding",
        kind="chapter", title="结论", parent_id=None, body="corrected",
        content=None, display_kind="", submission=correction,
    )
    assert saved["head"]["generation"] == 1
    finalized = finalize_published_submission(
        package_root=package, branch_id="main", submission=correction,
        finalize=lambda: {"git": {"committed": True}},
    )
    assert finalized["git"]["committed"] is True
    assert not created["paths"]["pending_submission"].exists()


def test_reconcile_keeps_finalize_gate_after_head_publish_crash(tmp_path: Path) -> None:
    package, created = _tree(tmp_path)
    begin_submission(
        package_root=package, branch_id="main", requested_sequence=None,
        logical_identity=_identity(), payload={"body": "valid"},
    )
    head = json.loads(created["paths"]["head"].read_text(encoding="utf-8"))
    write_head(created["paths"], {
        **head, "generation": 1, "locator_generation": 1,
    })
    assert reconcile_submission(package_root=package, branch_id="main") is True
    pending = json.loads(
        created["paths"]["pending_submission"].read_text(encoding="utf-8")
    )
    assert pending["phase"] == "published"
    assert pending["published_generation"] == 1


def test_cleanup_failure_cannot_roll_back_published_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package, created = _tree(tmp_path)
    submission = begin_submission(
        package_root=package, branch_id="main", requested_sequence=None,
        logical_identity=_identity(), payload={"body": "valid"},
    )
    saved = add_component(
        package_root=package, branch_id="main", component_id="finding",
        kind="chapter", title="结论", parent_id=None, body="valid",
        content=None, display_kind="", submission=submission,
    )
    monkeypatch.setattr(
        submission_finalize,
        "remove_pending",
        lambda _paths: (_ for _ in ()).throw(OSError("cleanup failed")),
    )

    with pytest.raises(OSError, match="cleanup failed"):
        finalize_published_submission(
            package_root=package, branch_id="main", submission=submission,
            finalize=lambda: {"git": {"committed": True}},
        )

    assert saved["head"]["generation"] == 1
    assert created["paths"]["pending_submission"].exists()
    assert (
        created["paths"]["root"] / saved["head"]["root_ref"]
    ).is_file()
    monkeypatch.undo()
    replayed = finalize_published_submission(
        package_root=package, branch_id="main", submission=submission,
        finalize=lambda: (_ for _ in ()).throw(AssertionError("must not rerun")),
    )
    assert replayed["git"]["committed"] is True
    assert not created["paths"]["pending_submission"].exists()
