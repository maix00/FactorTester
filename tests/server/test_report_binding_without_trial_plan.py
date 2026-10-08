"""A run may mount itself into a report independently from sample-use policy.

The report workspace, branch and an explicit parent component are enough to
freeze where a Job result goes.
"""

from __future__ import annotations

import pytest

from server.services.research_run_report_binding import normalize_report_binding

_HASH = "a" * 64


def _binding():
    return {
        "profile_ref": "profile:maxb",
        "report_workspace_id": "report-abc",
        "branch_id": "main",
        "report_id": "report:v1:TvyK4dXAippiobAiXU1MYGyJ",
        "report_generation": 31,
        "report_head_hash": _HASH,
        "report_parent_id": "s8",
    }


def test_report_direct_binding_has_no_sample_policy_dependency():
    out = normalize_report_binding(_binding())
    assert out["report_parent_id"] == "s8"


def test_graph_identity_fields_are_rejected():
    with pytest.raises(ValueError, match="complete frozen ReportBranch"):
        normalize_report_binding({
            **_binding(), "instance_id": "retired-instance",
        })
