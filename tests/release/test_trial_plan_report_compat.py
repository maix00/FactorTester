from __future__ import annotations

from tools.cli.release.research_reporting.markdown import MarkdownReportTarget
from tools.cli.release.research_reporting.schema import canonical_report_snapshot
from tools.cli.release.research_reporting.workspace_schema import (
    initial_index,
    snapshot_identity,
)


def _snapshot() -> dict:
    return snapshot_identity(
        workspace_id="workspace-1",
        report_workspace_id="report-1",
        branch_id="main",
        title="Report",
        status="draft",
        factor_family_versions=["family:sha256:" + "a" * 64],
    )


def test_new_report_templates_do_not_emit_trial_plan_sentinels() -> None:
    index = initial_index(
        report_workspace_id="report-1",
        workspace_id="workspace-1",
        branch_id="main",
        branch_ref="branch:main",
        title="Report",
        status="draft",
        factor_family_versions=["family:sha256:" + "a" * 64],
    )
    snapshot = _snapshot()

    assert "trial_plan_hash" not in index["branches"][0]
    assert "trial_plan_hash" not in snapshot


def test_report_reader_preserves_legacy_hashing_and_keeps_real_legacy_hash() -> None:
    empty = _snapshot()
    empty["trial_plan_hash"] = ""
    canonical_empty = canonical_report_snapshot(empty)
    assert canonical_empty["trial_plan_hash"] == ""
    assert "TrialPlan" not in MarkdownReportTarget().render(empty).decode()

    legacy = _snapshot()
    legacy["trial_plan_hash"] = "b" * 64
    output = MarkdownReportTarget().render(legacy).decode()
    assert "历史 TrialPlan" in output
    assert "b" * 64 in output
