"""A run may mount itself into a report without a TrialPlan.

The work package, branch and an explicit report parent component are enough to
freeze where a job's special section goes; requiring a frozen research-graph
trial identity for every mount made ordinary runs unable to contribute results.
"""

from __future__ import annotations

import pytest

from server.services.research_run_report_binding import normalize_report_binding

_HASH = "a" * 64


def _binding(origin="report_direct"):
    return {
        "binding_origin": origin,
        "profile_ref": "profile:maxb",
        "work_package_ref": "work-package:report-abc",
        "branch_id": "main",
        "report_id": "report:v1:TvyK4dXAippiobAiXU1MYGyJ",
        "report_generation": 31,
        "report_head_hash": _HASH,
        "report_parent_id": "s8",
    }


def test_report_direct_binding_needs_no_trial_plan():
    out = normalize_report_binding(_binding(), trial_binding=None, branch_snapshot={})
    assert out["binding_origin"] == "report_direct"
    assert out["report_parent_id"] == "s8"
    assert out["execution_node"] == ""


def test_report_direct_binding_rejects_a_trial_binding():
    with pytest.raises(ValueError, match="must not carry a trial binding"):
        normalize_report_binding(_binding(), trial_binding={"binding_origin": "agent_direct"}, branch_snapshot={})


def test_agent_direct_binding_still_requires_its_trial_plan():
    with pytest.raises(ValueError, match="requires its TrialPlan"):
        normalize_report_binding(_binding("agent_direct"), trial_binding=None, branch_snapshot={})


def test_unknown_origin_is_rejected():
    with pytest.raises(ValueError, match="agent_direct or report_direct"):
        normalize_report_binding(_binding("graph_trial"), trial_binding=None, branch_snapshot={})


def test_graph_binding_still_requires_the_frozen_identity():
    payload = {k: v for k, v in _binding().items() if k != "binding_origin"}
    payload.pop("report_parent_id", None)
    payload["instance_id"] = "instance-1"
    with pytest.raises(ValueError, match="requires trial_binding"):
        normalize_report_binding(payload, trial_binding=None, branch_snapshot={})
