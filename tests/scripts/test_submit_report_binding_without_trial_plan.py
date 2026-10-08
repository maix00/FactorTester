"""Report-bound Runs freeze a ReportBranch location independently of plans."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SUBMIT = REPO / "tools" / "cli" / "commands" / "research.py"
BINDING = REPO / "tools" / "cli" / "commands" / "research_report_job_binding.py"
ARTIFACTS = REPO / "tools" / "cli" / "release" / "research_reporting" / "job_artifacts.py"


def test_submit_no_longer_demands_a_trial_binding_for_report_mounts():
    source = SUBMIT.read_text(encoding="utf-8")
    assert "报告绑定需要 --trial-binding-file" not in source
    assert "--report-parent-id 仅用于 agent_direct TrialPlan" not in source
    assert '"--report-workspace-id"' in source
    assert "绑定报告必须提供 --report-parent-id" in source
    assert "if has_report_scope and not report_parent_id" in source
    assert 'report_binding = freeze_report_binding(' in source


def test_binding_freezer_freezes_report_workspace_branch_and_parent_without_trial_plan():
    source = BINDING.read_text(encoding="utf-8")
    assert "trial_binding" not in source
    assert "def freeze_report_binding(" in source
    assert '"report_workspace_id": scope.report_workspace_id' in source
    assert '"branch_id": scope.branch_id' in source
    assert '"report_parent_id": parent_id' in source
    assert "instance_id" not in source
    assert "work_package_ref" not in source


def test_collect_report_requires_the_exact_report_workspace_branch_and_parent():
    source = ARTIFACTS.read_text(encoding="utf-8")
    assert 'binding.get("report_workspace_id")' in source
    assert 'binding.get("branch_id")' in source
    assert 'binding.get("report_parent_id")' in source
    assert "work_package_ref" not in source
    assert "binding_origin" not in source
