from __future__ import annotations

import pytest

from server.services.research_step.contracts import (
    build_inspect_contract,
    build_prepare_contract,
)
from tools.cli.protocols.research_step import (
    contract_hash,
    validate_prepare_contract,
)


def _next_packet() -> dict:
    return {
        "graph": "factor-research@v9",
        "context_ref": "sha256:" + "1" * 64,
        "branch": {
            "instance_id": "instance-1",
            "branch_id": "branch-1",
            "work_package_id": "work-package-1",
            "workspace_id": "workspace-1",
            "current_owner_profile_ref": "profile:maxa",
            "trial_plan_hash": "2" * 64,
        },
        "node": {"node_id": "trial_execution", "kind": "execution"},
        "candidate_edges": [{
            "edge_id": "trial_execution__result_audit",
            "to_node": "result_audit",
            "readiness": "blocked",
        }],
        "capabilities": [{
            "capability_id": "factor-validation.cross-sectional-ic",
            "status": "bound",
        }],
        "node_report_requirement_refs": ["report.execution-status"],
        "changed_refs": ["evidence:old"],
        "current_obligations": [{"obligation_id": "obligation-1"}],
    }


def _execution() -> dict:
    return {
        "instance_id": "instance-1",
        "branch_id": "branch-1",
        "trial_plan_hash": "2" * 64,
        "latest_trace_id": "trace-1",
        "checkpoint": {
            "projection_hash": "3" * 64,
            "current_action_status": "unreleased",
        },
        "current_action": {
            "action_id": "action-1",
            "stage_id": "selection",
            "input_hash": "4" * 64,
            "execution_mode": "job",
            "expected_evidence_kind": "job_attempt",
            "run_spec_hashes": ["5" * 64, "6" * 64],
            "comparison_ids": ["comparison-1"],
            "obligation_refs": ["obligation-1"],
        },
        "allowed_operations": ["release"],
        "operation_payload_contracts": {
            "release": {"required_fields": []},
        },
        "trial_plan": {
            "comparisons": [{
                "comparison_id": "comparison-1",
                "members": [
                    {"trial_role": "day"},
                    {"trial_role": "night"},
                    {"trial_role": "candidate"},
                ],
            }],
            "must_not": "leak",
        },
    }


def test_inspect_is_compact_and_authoritatively_bound() -> None:
    value = build_inspect_contract(_next_packet(), _execution())

    assert value["binding"] == {
        "profile_ref": "profile:maxa",
        "work_package_id": "work-package-1",
        "instance_id": "instance-1",
        "branch_id": "branch-1",
    }
    assert value["action"]["run_spec_hashes"] == ["5" * 64, "6" * 64]
    assert value["cas"] == {
        "latest_trace_id": "trace-1",
        "checkpoint_hash": "3" * 64,
    }
    assert "trial_plan" not in value
    assert "changed_refs" not in value
    assert "current_obligations" not in value
    assert "stdout" not in str(value)


def test_prepare_multiple_configurations_returns_truthful_gap() -> None:
    inspect = build_inspect_contract(_next_packet(), _execution())
    request = {
        "schema_version": 1,
        "context_ref": inspect["graph"]["context_ref"],
        "action_id": "action-1",
        "configurations": [
            {
                "configuration_id": "config-day",
                "configuration_revision": 4,
                "configuration_fingerprint": "7" * 64,
                "analyses": ["ic"],
                "trial_role": "day",
                "comparison_id": "comparison-1",
            },
            {
                "configuration_id": "config-night",
                "configuration_revision": 5,
                "configuration_fingerprint": "8" * 64,
                "analyses": ["ic"],
                "trial_role": "night",
                "comparison_id": "comparison-1",
            },
        ],
    }

    contract = build_prepare_contract(inspect, request)

    assert contract["execution_ready"] is False
    assert len(contract["configuration_requests"]) == 2
    assert contract["capability_gaps"] == [{
        "capability_id": "research-run.immutable-configuration-snapshot",
        "reason": (
            "stable immutable configuration snapshot preview is unavailable"
        ),
    }]
    assert "run_spec_hash" not in str(contract["configuration_requests"])
    assert validate_prepare_contract(contract)["valid"] is True


def test_validate_rejects_tampered_contract() -> None:
    inspect = build_inspect_contract(_next_packet(), _execution())
    contract = build_prepare_contract(inspect, {
        "schema_version": 1,
        "context_ref": inspect["graph"]["context_ref"],
        "action_id": "action-1",
        "configurations": [{
            "configuration_id": "config-day",
            "configuration_revision": 4,
            "configuration_fingerprint": "7" * 64,
            "analyses": ["ic"],
            "trial_role": "day",
            "comparison_id": "comparison-1",
        }],
    })
    contract["binding"]["work_package_id"] = "attacker-package"

    with pytest.raises(ValueError, match="contract_hash"):
        validate_prepare_contract(contract)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("binding", "work_package_id"), "", "binding"),
        (("cas", "checkpoint_hash"), "bad", "sha256"),
        (("action", "execution_mode"), "manual", "job Evidence Action"),
        (("capability_gaps",), [], "capability_gaps"),
    ],
)
def test_deep_validation_rejects_rehashed_forgery(
    path, value, message,
) -> None:
    inspect = build_inspect_contract(_next_packet(), _execution())
    contract = build_prepare_contract(inspect, {
        "schema_version": 1,
        "context_ref": inspect["graph"]["context_ref"],
        "action_id": "action-1",
        "configurations": [{
            "configuration_id": "config-day",
            "configuration_revision": 4,
            "configuration_fingerprint": "7" * 64,
            "analyses": ["ic"],
            "trial_role": "day",
            "comparison_id": "comparison-1",
        }],
    })
    target = contract
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    contract["contract_hash"] = contract_hash(contract)

    with pytest.raises(ValueError, match=message):
        validate_prepare_contract(contract)


def test_non_job_action_cannot_prepare_runspecs() -> None:
    execution = _execution()
    execution["current_action"]["execution_mode"] = "agent"
    execution["current_action"]["expected_evidence_kind"] = "semantic"
    inspect = build_inspect_contract(_next_packet(), execution)

    with pytest.raises(ValueError, match="job Evidence Action"):
        build_prepare_contract(inspect, {
            "schema_version": 1,
            "context_ref": inspect["graph"]["context_ref"],
            "action_id": "action-1",
            "configurations": [{
                "configuration_id": "config-day",
                "configuration_revision": 4,
                "configuration_fingerprint": "7" * 64,
                "analyses": ["ic"],
                "trial_role": "day",
                "comparison_id": "comparison-1",
            }],
        })


def test_large_packet_is_summarized_and_exactly_sized() -> None:
    packet = _next_packet()
    packet["capabilities"] = [
        {
            "capability_id": f"capability-{index}",
            "status": "bound",
            "descriptor_hash": f"descriptor-{index}",
            "contract": {"body": "never leak" * 100},
        }
        for index in range(24)
    ]
    execution = _execution()
    execution["operation_payload_contracts"]["release"] = {
        "required_fields": [],
        "full_schema": {"never": "leak"},
    }

    value = build_inspect_contract(packet, execution)

    assert "contract" not in str(value["capabilities"])
    assert value["operation_payload_contracts"] == {
        "release": {"required_fields": []},
    }
