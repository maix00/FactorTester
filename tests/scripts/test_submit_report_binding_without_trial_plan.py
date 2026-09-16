"""The submit command mounts reports without demanding a TrialPlan file."""

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
    assert "绑定报告必须提供 --report-parent-id" in source
    assert "standalone_report_run = has_report_scope and trial_binding is None" in source


def test_binding_freezer_supports_a_standalone_origin():
    source = BINDING.read_text(encoding="utf-8")
    assert "trial_binding: dict[str, Any] | None = None" in source
    assert '"report_direct"' in source


def test_collect_report_accepts_both_mount_origins():
    source = ARTIFACTS.read_text(encoding="utf-8")
    assert 'in {"agent_direct", "report_direct"}' in source
