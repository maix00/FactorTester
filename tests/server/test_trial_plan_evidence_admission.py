"""Deterministic Evidence Admission Gate tests for TrialPlan v5."""

from __future__ import annotations

from copy import deepcopy

import pytest

from server.services.research_graph.protocol import json_hash
from server.services.research_graph.research_cycle.evidence import (
    validate_agent_evidence_envelope,
)
from server.services.research_graph.trial_plan import (
    admit_current_action,
    initial_execution_checkpoint,
    transition_action_status,
    trial_plan_hash,
)
from tests.server.test_trial_plan_contract_v5 import trial_plan_v5


def _record(plan: dict, *, trusted: bool = True) -> dict:
    action = plan["evidence_actions"][0]
    snapshot = {
        "schema_version": 1,
        "action_id": action["action_id"],
        "action_hash": json_hash(action),
        "stage_id": action["stage_id"],
        "input_hash": action["input_hash"],
        "execution_mode": action["execution_mode"],
        "capability_requirement_ref": action["capability_requirement_ref"],
        "expected_evidence_kind": action["expected_evidence_kind"],
        "evidence_contract_ref": action["evidence_contract_ref"],
        "obligation_refs": action["obligation_refs"],
        "run_spec_hashes": action["run_spec_hashes"],
        "comparison_ids": action["comparison_ids"],
        "release_checkpoint_hash": "7" * 64,
    }
    envelope = validate_agent_evidence_envelope({
        "schema_version": 2,
        "envelope_id": "job-attempt:job-1",
        "evidence_kind": "job_attempt",
        "source_refs": ["research-job:job-1", "research-run:run-1"],
        "identity_refs": {
            "contract_hash": plan["decision_contract_hash"],
            "methodology_hash": plan["methodology_hash"],
            "trial_plan_hash": trial_plan_hash(plan),
            "run_spec_hash": action["run_spec_hashes"][0],
        },
        "facts": {
            "job_id": "job-1",
            "run_id": "run-1",
            "kind": "ic",
            "status": "succeeded" if trusted else "failed",
            "attempt": 1,
            "trial_stage": "validation",
            "net_return_series_available": False,
            "assurance": {
                "policy_hash": "8" * 64,
                "backend_revision": "backend-1",
                "disposition": "trusted" if trusted else "rejected",
                "anomaly_codes": [] if trusted else ["worker_failed"],
            },
        },
        "metric_refs": ["result-summary:sha256:" + "9" * 64],
        "artifact_refs": ["artifact-manifest:sha256:" + "a" * 64],
        "hypotheses_tested": 0,
        "stop_condition": None,
        "limitations": [],
        "conflicts": [],
    })
    return {
        "trial_binding": {
            "trial_plan_hash": trial_plan_hash(plan),
            "trial_plan_schema_version": 5,
            "trial_stage_id": action["stage_id"],
            "evidence_action_id": action["action_id"],
            "evidence_action_binding_hash": json_hash(snapshot),
            "evidence_action_binding": snapshot,
        },
        "envelope": envelope,
    }


def _ready(plan: dict, record: dict) -> dict:
    checkpoint = initial_execution_checkpoint(
        trial_plan=plan,
        expected_trial_plan_hash=trial_plan_hash(plan),
        execution_node="trial_execution",
    )
    checkpoint = transition_action_status(checkpoint, target="released")
    checkpoint = transition_action_status(checkpoint, target="running")
    return transition_action_status(
        checkpoint,
        target="evidence_ready",
        evidence_refs=["evidence:" + record["envelope"]["envelope_hash"]],
    )


def test_gate_admits_complete_trusted_action_without_agent_judgment() -> None:
    plan = trial_plan_v5()
    record = _record(plan)

    decision = admit_current_action(
        _ready(plan, record),
        trial_plan=plan,
        evidence_records=[record],
    )

    assert decision["qualification"] == "eligible"
    assert decision["reason_codes"] == []
    assert decision["checkpoint"]["current_action_status"] == "admitted"


def test_gate_marks_untrusted_terminal_result_rejected() -> None:
    plan = trial_plan_v5()
    record = _record(plan, trusted=False)

    decision = admit_current_action(
        _ready(plan, record),
        trial_plan=plan,
        evidence_records=[record],
    )

    assert decision["qualification"] == "rejected"
    assert decision["reason_codes"] == [
        "job_not_succeeded",
        "terminal_assurance_anomaly",
        "terminal_assurance_untrusted",
    ]


def test_gate_rejects_stale_action_binding_and_incomplete_run_set() -> None:
    plan = trial_plan_v5()
    record = _record(plan)
    stale = deepcopy(record)
    stale["trial_binding"]["evidence_action_binding"]["input_hash"] = "f" * 64
    with pytest.raises(ValueError, match="binding hash mismatch"):
        admit_current_action(
            _ready(plan, record),
            trial_plan=plan,
            evidence_records=[stale],
        )

    with pytest.raises(ValueError, match="RunSpec set mismatch"):
        admit_current_action(
            _ready(plan, record),
            trial_plan=plan,
            evidence_records=[],
        )
