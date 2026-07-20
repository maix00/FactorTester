"""Generate blinded Batch 6 Decision Contracts and initial Graph evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from batch6_case_specs import CASES
from server.services.research_graph.research_cycle import (
    validate_decision_contract,
    validate_research_claim,
    validate_research_cycle_checkpoint,
    validate_verification_obligation,
)
from server.services.research_graph.branch.research_cycle import (
    prepare_research_cycle_trace,
)
from server.services.research_graph.protocol import (
    serialize_bounded_trace_evidence,
)
from server.services.research_graph.trial_plan import (
    canonical_trial_plan,
    trial_plan_hash,
)


GRAPH_HASH = "16545c8bfead87c407806f0f94d448353b12aecd6fb5767ba85070bb2ca0e22d"
METHODOLOGY_HASH = (
    "b705ae825afa8033e235b9e5f7a43e51b25cb807f13366467bb4f088dc2dec34"
)


def _contract(case_name: str, case: dict) -> dict:
    return validate_decision_contract({
        "schema_version": 1,
        "contract_id": f"issue140-{case_name}-contract-v1",
        "work_package_ref": "issue140-batch6-all-workspace-factors",
        "branch_ref": f"branch:{case['branch_id']}",
        "decision": case["decision"],
        "permitted_use": (
            "local_research_acceptance_only_no_production_or_live_trading"
        ),
        "scope": {
            "workspace_id": case["workspace_id"],
            "configuration_id": case["configuration_id"],
            "configuration_revision": case["configuration_revision"],
            "factor_family": case["factor_family"],
            "factor_family_version": case["factor_family_version"],
            "factor_alias": case["factor_alias"],
            "product_group": "china_futures",
            "frequency": "configured_signal_frequency",
            "sample_start": case["sample_start"],
            "sample_end": case["sample_end"],
        },
        "search_design": {
            "analyses": case["analyses"],
            "sample_role": case["sample_role"],
            "result_dependent_extension": "new_trial_plan_version_required",
            "sealed_baseline_access": (
                "forbidden_until_new_graph_closure"
                if case_name == "sgccs"
                else "not_applicable"
            ),
        },
        "stopping_rule_refs": [
            "stop_on_terminal_backend_failure",
            "stop_on_unresolved_identity_conflict",
            "stop_at_declared_sample_and_trial_frontier",
        ],
        "graph_hash": GRAPH_HASH,
        "methodology_hash": METHODOLOGY_HASH,
        "blocking_policy": {
            "decision_blocking_obligations": (
                "must_be_discharged_bounded_or_explicitly_block_closure"
            ),
            "selection_evidence": "cannot_authorize_confirmation_claim",
            "backend_jobs": "continue_when_unaffected",
        },
    })


def _claim(case_name: str, case: dict, contract_hash: str) -> dict:
    return validate_research_claim({
        "schema_version": 1,
        "claim_id": f"issue140-{case_name}-claim-v1",
        "contract_hash": contract_hash,
        "claim_ref": case["claim_ref"],
        "claim_type": case["claim_type"],
        "scope": {
            "factor_family": case["factor_family"],
            "factor_family_version": case["factor_family_version"],
            "product_group": "china_futures",
            "sample_role": case["sample_role"],
        },
        "evidence_state": "unknown",
        "evidence_refs": [],
    })


def _obligations(case_name: str, case: dict, contract_hash: str) -> list[dict]:
    claim_id = f"issue140-{case_name}-claim-v1"
    return [
        validate_verification_obligation({
            "schema_version": 1,
            "obligation_id": obligation_id,
            "contract_hash": contract_hash,
            "claim_ids": [claim_id],
            "obligation_kind": obligation_kind,
            "epistemic_question": question,
            "scope": {
                "factor_family": case["factor_family"],
                "product_group": "china_futures",
                "sample_role": case["sample_role"],
            },
            "discharge_criterion": {"criterion": criterion},
            "status": "open",
            "materiality": "decision_blocking",
            "methodology_hash": METHODOLOGY_HASH,
            "created_event_ref": "planning:issue140-batch6-v1",
        })
        for obligation_id, obligation_kind, question, criterion
        in case["obligations"]
        if obligation_id in set(case["initial_obligation_ids"])
    ]


def _trial_plan(
    case_name: str,
    case: dict,
    *,
    contract_hash: str,
) -> dict:
    compact = (
        {
            "plan_id": "i140-s-v1",
            "claim_ref": "i140-s-claim",
            "family_ref": "i140-s-f1",
            "sample_ref": "s-replay",
            "comparison_id": "s-primary",
            "primary": "net_ordering",
            "secondary": ["grid_robustness", "turnover", "assurance"],
            "multiplicity": "declared-grid",
        }
        if case_name == "sgccs"
        else {
            "plan_id": "i140-t-v1",
            "claim_ref": "i140-t-claim",
            "family_ref": "i140-t-f1",
            "sample_ref": "t-select",
            "comparison_id": "t-primary",
            "primary": "rank_ic",
            "secondary": ["distribution", "type", "net_backtest"],
            "multiplicity": "single-preregistered",
        }
    )
    outcomes = {
        "primary": [compact["primary"]],
        "secondary": compact["secondary"],
    }
    run_hashes = list(case["run_spec_hashes"].values())
    return canonical_trial_plan({
        "schema_version": 4,
        "trial_plan_id": compact["plan_id"],
        "version": 1,
        "hypothesis_ref": compact["claim_ref"],
        "trial_family": compact["family_ref"],
        "protocol_ref": "runspec-v1",
        "outcomes": outcomes,
        "sample_roles": [{
            "sample_ref": compact["sample_ref"],
            "sample_hash": case["sample_hash"],
            "role": case["sample_role"],
            "run_spec_hashes": run_hashes,
        }],
        "comparisons": [{
            "comparison_id": compact["comparison_id"],
            "members": [{
                "run_spec_hash": run_hash,
                "trial_role": case["sample_role"],
            } for run_hash in run_hashes],
        }],
        "stopping": {
            "rule_ref": "terminal-or-id",
            "monitored_outcomes": outcomes["primary"],
            "parameters": {
                "required_terminal_assurance": True,
                "max_run_attempts": 1,
            },
        },
        "multiplicity": {
            "method_ref": compact["multiplicity"],
            "family_ref": compact["family_ref"],
            "dependence_assumptions": ["shared-sample"],
        },
        "criteria": {
            "rejection_ref": "id-or-null",
            "revision_ref": "conflict",
            "continuation_ref": "new-plan",
        },
        "decision_contract_hash": contract_hash,
        "methodology_hash": METHODOLOGY_HASH,
        "obligation_refs": case["initial_obligation_ids"],
        "parent_trial_plan_hash": None,
        "stage_policy": {
            "ordered_stages": [case["sample_role"]],
            "entry_stage": case["sample_role"],
            "entry_basis_ref": f"decision-contract:{case_name}-current-stage",
        },
    })


def _trial_freeze_evidence(
    *,
    checkpoint: dict,
    plan: dict,
    plan_hash: str,
) -> tuple[dict, int]:
    cycle_update = {
        "schema_version": 1,
        "parent_trace_ref": "trace:" + ("0" * 32),
        "expected_base_hash": checkpoint["projection_hash"],
        "events": [{
            "event_type": "trial_plan_bound",
            "from_hash": "",
            "to_hash": plan_hash,
        }],
    }
    trace_event, projected = prepare_research_cycle_trace(
        update=cycle_update,
        previous_checkpoint=checkpoint,
        latest_trace_id="0" * 32,
    )
    evidence = {
        "actionable_obligations_planned_or_bounded": True,
        "selection_and_trial_plan_frozen": True,
        "trial_plan_hash": plan_hash,
        "trial_plan": plan,
        "research_cycle": cycle_update,
    }
    persisted = {
        key: value
        for key, value in evidence.items()
        if key != "research_cycle"
    }
    persisted["research_cycle"] = trace_event
    persisted["research_cycle_checkpoint"] = projected
    serialized = serialize_bounded_trace_evidence(persisted)
    return evidence, len(serialized.encode())


def build_case(
    case_name: str,
    case: dict,
    *,
    planning_invocation_id: str,
) -> dict:
    contract = _contract(case_name, case)
    claim = _claim(case_name, case, contract["contract_hash"])
    obligations = _obligations(
        case_name,
        case,
        contract["contract_hash"],
    )
    checkpoint = validate_research_cycle_checkpoint({
        "schema_version": 1,
        "contract_hash": contract["contract_hash"],
        "trial_plan_hash": "",
        "methodology_hash": METHODOLOGY_HASH,
        "claims": [claim],
        "obligations": obligations,
        "pending_adjudications": [],
        "pending_closure": None,
        "closure": None,
    })
    plan = _trial_plan(
        case_name,
        case,
        contract_hash=contract["contract_hash"],
    )
    plan_hash = trial_plan_hash(plan)
    freeze_evidence, freeze_trace_bytes = _trial_freeze_evidence(
        checkpoint=checkpoint,
        plan=plan,
        plan_hash=plan_hash,
    )
    bootstrap_evidence = {
        "hypothesis_frozen": True,
        "obligation_discovery_checkpoint_fresh": True,
        "evidence_refs": [
            f"decision-contract:{contract['contract_hash']}",
            *[
                f"runspec-preview:{run_hash}"
                for run_hash in case["run_spec_hashes"].values()
            ],
        ],
        "agent_invocation_ids": [planning_invocation_id],
        "research_cycle": {
            "schema_version": 1,
            "parent_trace_ref": "",
            "initial_checkpoint": checkpoint,
            "expected_base_hash": checkpoint["projection_hash"],
            "events": [],
        },
    }
    return {
        "case": case_name,
        "decision_contract": contract,
        "initial_claim": claim,
        "initial_obligations": obligations,
        "initial_checkpoint": checkpoint,
        "trial_plan": plan,
        "trial_plan_hash": plan_hash,
        "trial_binding": {
            "instance_id": case["instance_id"],
            "branch_id": case["branch_id"],
            "trial_plan": plan,
            "trial_plan_hash": plan_hash,
            "trial_plan_version": plan["version"],
            "trial_role": case["sample_role"],
            "comparison_id": (
                "s-primary" if case_name == "sgccs" else "t-primary"
            ),
        },
        "trial_freeze_evidence": freeze_evidence,
        "trial_freeze_trace_bytes": freeze_trace_bytes,
        "run_spec_preview": {
            "run_spec_hashes": case["run_spec_hashes"],
            "configuration_fingerprint": case["configuration_fingerprint"],
            "configuration_revision": case["configuration_revision"],
            "analyses": case["analyses"],
        },
        "bootstrap_evidence": bootstrap_evidence,
        "capability_resolution": {
            "node_id": "capability_resolution",
            "bindings": [],
            "gaps": [],
            "triggered_conditional_bindings": [],
            "triggered_conditional_gaps": [],
            "undetermined_conditions": [],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--planning-invocation-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    package = {
        "schema_version": 1,
        "blindness_seal": {
            "sgccs_v1_result_access": "forbidden_until_new_graph_closure",
            "historical_result_metrics_loaded": False,
        },
        "graph": {
            "graph_ref": "factor-research@5",
            "graph_hash": GRAPH_HASH,
            "methodology_hash": METHODOLOGY_HASH,
        },
        "planning_invocation_id": args.planning_invocation_id,
        "cases": {
            name: build_case(
                name,
                case,
                planning_invocation_id=args.planning_invocation_id,
            )
            for name, case in CASES.items()
        },
    }
    package_path = args.output_dir / "batch6-live-research-contracts.json"
    package_path.write_text(
        json.dumps(package, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    for name, value in package["cases"].items():
        for key in (
            "bootstrap_evidence",
            "capability_resolution",
            "trial_freeze_evidence",
            "trial_binding",
        ):
            path = args.output_dir / f"{name}-{key.replace('_', '-')}.json"
            path.write_text(
                json.dumps(
                    value[key],
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
    print(json.dumps({
        "package_path": str(package_path),
        "cases": {
            name: {
                "contract_hash": value["decision_contract"]["contract_hash"],
                "checkpoint_hash": (
                    value["initial_checkpoint"]["projection_hash"]
                ),
                "trial_plan_hash": value["trial_plan_hash"],
                "run_spec_hashes": (
                    value["run_spec_preview"]["run_spec_hashes"]
                ),
            }
            for name, value in package["cases"].items()
        },
    }, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
