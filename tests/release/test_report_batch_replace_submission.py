from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.cli.commands import research_report_submission
from tools.cli.commands.research_report_submission import begin_batch_submission
from tools.cli.commands.research_report_submission_errors import (
    SequencedSubmissionError,
    SubmissionGateUsageError,
)
from tools.cli.commands.research_report_submission_identity import batch_identity
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
    initialize_tree,
)


def _scope(tmp_path: Path) -> SimpleNamespace:
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
    return SimpleNamespace(package_root=package, branch_id="main")


def _replace(component_id: str, body: str = "正文") -> dict[str, object]:
    return {
        "op": "replace", "component_id": component_id,
        "title": "章节", "body": body, "content": None,
        "display_kind": "finding",
    }


def test_replace_identity_tracks_target_but_allows_content_correction() -> None:
    first = batch_identity([_replace("one", "错误")])
    corrected = batch_identity([_replace("one", "正确")])
    other = batch_identity([_replace("two", "正确")])

    assert first == corrected
    assert first != other
    assert first == batch_identity([{
        "op": "bind", "component_id": "one", "binding": {},
    }])


def test_replace_runs_component_preflight_and_uses_generated_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _scope(tmp_path)
    generated = [{
        "binding_id": "reference-one", "kind": "job",
        "target_ref": "job:one", "label": "任务",
        "data": {"status": "succeeded"},
    }]
    calls: list[dict[str, object]] = []

    def preflight(**values):
        calls.append(values)
        return generated, []

    monkeypatch.setattr(
        research_report_submission, "checked_component_preflight", preflight,
    )
    submission, enriched = begin_batch_submission(
        scope=scope, requested_sequence=None,
        operations=[_replace("chapter")], as_json=False,
    )

    assert submission.sequence == 2
    assert calls[0]["component_id"] == "chapter"
    assert calls[0]["kind"] == "chapter"
    assert calls[0]["body"] == "正文"
    assert calls[0]["display_kind"] == "finding"
    assert enriched[0]["bindings"] == generated


def test_replace_rejects_even_empty_agent_bindings(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    operation = {**_replace("chapter"), "bindings": []}

    with pytest.raises(SequencedSubmissionError) as caught:
        begin_batch_submission(
            scope=scope, requested_sequence=None,
            operations=[operation], as_json=False,
        )

    assert caught.value.diagnostics[0]["code"] == "report.binding.agent_forbidden"


def test_forbidden_bind_can_be_corrected_to_replace_in_same_slot(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path)
    with pytest.raises(SequencedSubmissionError):
        begin_batch_submission(
            scope=scope, requested_sequence=None, as_json=False,
            operations=[{
                "op": "bind", "component_id": "chapter", "binding": {},
            }],
        )

    submission, enriched = begin_batch_submission(
        scope=scope, requested_sequence=2, as_json=False,
        operations=[_replace("chapter", "修正正文")],
    )
    assert submission.sequence == 2
    assert enriched[0]["op"] == "replace"


def test_unidentifiable_batch_is_rejected_before_reserving_sequence(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path)
    for operations in (
        [], [{"op": "invalid"}],
        [{"op": "invalid", "component_id": ""}],
    ):
        with pytest.raises(SubmissionGateUsageError):
            begin_batch_submission(
                scope=scope, requested_sequence=None,
                operations=operations, as_json=False,
            )
        pending = (
            scope.package_root / "branches" / "main" / "authoring"
            / "pending-submission.json"
        )
        assert not pending.exists()
