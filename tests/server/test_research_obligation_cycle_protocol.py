from __future__ import annotations

import pytest

from server.services.research_graph.research_cycle.adjudication import (
    validate_adjudication_pair,
    validate_adjudication_decision,
    validate_adjudication_proposal,
)
from server.services.research_graph.research_cycle.contracts import (
    validate_decision_contract,
    validate_research_claim,
)
from server.services.research_graph.research_cycle.closure import (
    validate_search_exhaustion_proposal,
)
from server.services.research_graph.research_cycle.evidence import (
    LegacyEvidenceAccessDenied,
    legacy_evidence_metadata,
    validate_agent_evidence_envelope,
)
from server.services.research_graph.research_cycle.obligations import (
    validate_verification_obligation,
)
from server.services.research_graph.research_cycle.methodology import (
    validate_methodology_change_proposal,
)


def test_agent_cannot_read_legacy_evidence_payload() -> None:
    legacy = {
        "schema_version": 1,
        "envelope_id": "legacy-1",
        "envelope_hash": "a" * 64,
        "decision": "continue",
        "metric_refs": ["metric:private"],
        "artifact_refs": ["artifact:private"],
    }

    with pytest.raises(
        LegacyEvidenceAccessDenied,
        match="legacy evidence is unavailable to Agents",
    ):
        validate_agent_evidence_envelope(legacy)

    assert legacy_evidence_metadata(legacy) == {
        "schema_version": 1,
        "envelope_id": "legacy-1",
        "envelope_hash": "a" * 64,
        "eligibility": "legacy_ineligible",
    }

    with pytest.raises(
        LegacyEvidenceAccessDenied,
        match="legacy evidence is unavailable to Agents",
    ):
        validate_agent_evidence_envelope({
            "schema_version": 1,
            "envelope_id": "minimal-legacy",
            "envelope_hash": "b" * 64,
        })


def test_current_evidence_accepts_facts_but_rejects_decisions() -> None:
    envelope = {
        "schema_version": 2,
        "envelope_id": "evidence-2",
        "evidence_kind": "job_attempt",
        "source_refs": ["job-attempt:17"],
        "identity_refs": {
            "contract_hash": "b" * 64,
            "trial_plan_hash": "c" * 64,
            "run_spec_hash": "d" * 64,
            "methodology_hash": "e" * 64,
        },
        "command": {
            "returncode": 0,
            "stdout_ref": "artifact:stdout:17",
            "stderr_ref": "",
        },
        "metric_refs": ["metric:ic:17"],
        "artifact_refs": ["artifact:report:17"],
        "hypotheses_tested": 3,
        "stop_condition": None,
        "limitations": ["one product scope"],
        "conflicts": [],
    }

    validated = validate_agent_evidence_envelope(envelope)
    assert len(validated["envelope_hash"]) == 64
    assert {
        key: value
        for key, value in validated.items()
        if key != "envelope_hash"
    } == envelope

    with pytest.raises(ValueError, match="must not contain decision"):
        validate_agent_evidence_envelope({
            **envelope,
            "decision": "supported_in_scope",
        })

    with pytest.raises(ValueError, match="envelope_hash mismatch"):
        validate_agent_evidence_envelope({
            **envelope,
            "envelope_hash": "f" * 64,
        })


def test_contract_can_add_a_novel_factor_specific_obligation() -> None:
    contract = validate_decision_contract({
        "schema_version": 1,
        "contract_id": "contract-17",
        "work_package_ref": "work-package:17",
        "branch_ref": "hypothesis-branch:17",
        "decision": "whether this factor is usable for bounded research",
        "permitted_use": "single-factor research only",
        "scope": {"product_group": "CN_FUTURES", "frequency": "DAY1"},
        "search_design": {"parameter_coverage": "adaptive"},
        "stopping_rule_refs": ["trial-plan:17"],
        "graph_hash": "1" * 64,
        "methodology_hash": "2" * 64,
        "blocking_policy": {"default": "material_only"},
    })
    claim = validate_research_claim({
        "schema_version": 1,
        "claim_id": "claim-17",
        "contract_hash": contract["contract_hash"],
        "claim_ref": "factor-claim:17",
        "claim_type": "bounded_predictive_relationship",
        "scope": {"product_group": "CN_FUTURES"},
        "evidence_state": "unknown",
        "evidence_refs": [],
    })
    obligation = validate_verification_obligation({
        "schema_version": 1,
        "obligation_id": "obligation-17",
        "contract_hash": contract["contract_hash"],
        "claim_ids": [claim["claim_id"]],
        "obligation_kind": "liquidity_discontinuity_near_delivery",
        "epistemic_question": (
            "Could delivery-window liquidity explain the observed relation?"
        ),
        "scope": {"delivery_window_days": 10},
        "discharge_criterion": {
            "method": "predeclared exclusion and perturbation comparison"
        },
        "status": "open",
        "materiality": "decision_blocking",
        "methodology_hash": "2" * 64,
        "created_event_ref": "trace:17",
    })

    assert obligation["obligation_kind"] == (
        "liquidity_discontinuity_near_delivery"
    )


def test_failed_preregistered_test_pairs_claim_and_obligation_changes() -> None:
    proposal = validate_adjudication_proposal({
        "schema_version": 1,
        "proposal_id": "adjudication-17",
        "contract_hash": "1" * 64,
        "trial_plan_hash": "6" * 64,
        "evidence_refs": ["evidence:17"],
        "methodology_hash": "2" * 64,
        "claim_evidence_delta": [{
            "claim_id": "claim-17",
            "from_state": "unknown",
            "to_state": "contradicted",
            "evidence_grade": "preregistered",
            "scope": {"sample": "confirmatory"},
        }],
        "obligation_delta": [{
            "obligation_id": "obligation-17",
            "from_state": "open",
            "to_state": "discharged",
            "criterion_ref": "trial-plan:17",
        }],
        "decision_warrant": {
            "finding_refs": ["evidence:17#criterion"],
            "rule_refs": ["trial-plan:17#rejection-rule"],
            "inference_type": "preregistered",
            "preregistered": True,
            "alternative_refs": [],
            "limitation_refs": [],
            "reentry_predicates": [],
            "required_authority": "preregistered_rule",
        },
    })
    decision = validate_adjudication_decision({
        "schema_version": 1,
        "decision_id": "decision-17",
        "proposal_hash": proposal["proposal_hash"],
        "disposition": "accepted",
        "authority_class": "preregistered_rule",
        "authority_ref": "trial-plan:17#rejection-rule",
        "methodology_hash": "2" * 64,
    })

    assert proposal["claim_evidence_delta"][0]["to_state"] == "contradicted"
    assert proposal["obligation_delta"][0]["to_state"] == "discharged"
    assert decision["proposal_hash"] == proposal["proposal_hash"]
    assert validate_adjudication_pair(
        proposal,
        decision,
        expected_contract_hash="1" * 64,
        expected_trial_plan_hash="6" * 64,
        expected_methodology_hash="2" * 64,
    )[1]["decision_id"] == "decision-17"


def test_post_hoc_support_is_exploratory_and_opens_confirmation_duty() -> None:
    proposal = {
        "schema_version": 1,
        "proposal_id": "adjudication-18",
        "contract_hash": "1" * 64,
        "trial_plan_hash": "6" * 64,
        "evidence_refs": ["evidence:18"],
        "methodology_hash": "2" * 64,
        "claim_evidence_delta": [{
            "claim_id": "claim-18",
            "from_state": "unknown",
            "to_state": "supported_in_scope",
            "evidence_grade": "exploratory",
            "scope": {"sample": "exploratory"},
        }],
        "obligation_delta": [{
            "obligation_id": "confirm-18",
            "from_state": "absent",
            "to_state": "open",
            "criterion_ref": "methodology:confirmatory-test",
        }],
        "decision_warrant": {
            "finding_refs": ["evidence:18#result"],
            "rule_refs": ["methodology:exploratory-result"],
            "inference_type": "post_hoc",
            "preregistered": False,
            "alternative_refs": [],
            "limitation_refs": ["limitation:post-hoc"],
            "reentry_predicates": [],
            "required_authority": "independent_reviewer",
        },
    }

    assert validate_adjudication_proposal(
        proposal
    )["claim_evidence_delta"][0]["evidence_grade"] == "exploratory"

    proposal["decision_warrant"]["required_authority"] = "preregistered_rule"
    with pytest.raises(
        ValueError,
        match="post_hoc inference cannot use preregistered_rule",
    ):
        validate_adjudication_proposal(proposal)


def test_obligation_discovery_requires_an_explicit_claim_noop() -> None:
    proposal = {
        "schema_version": 1,
        "proposal_id": "adjudication-19",
        "contract_hash": "1" * 64,
        "trial_plan_hash": "6" * 64,
        "evidence_refs": ["trace:first-principles-review:19"],
        "methodology_hash": "2" * 64,
        "claim_evidence_delta": [],
        "claim_delta_noop_reason": (
            "The review found a question, not new empirical Claim evidence."
        ),
        "obligation_delta": [{
            "obligation_id": "mechanism-19",
            "from_state": "absent",
            "to_state": "open",
            "criterion_ref": "methodology:mechanism-discrimination",
        }],
        "decision_warrant": {
            "finding_refs": ["trace:first-principles-review:19"],
            "rule_refs": ["methodology:obligation-discovery"],
            "inference_type": "semantic",
            "preregistered": False,
            "alternative_refs": ["alternative:inventory-pressure"],
            "limitation_refs": [],
            "reentry_predicates": [],
            "required_authority": "independent_reviewer",
        },
    }

    assert validate_adjudication_proposal(
        proposal
    )["claim_evidence_delta"] == []

    proposal.pop("claim_delta_noop_reason")
    with pytest.raises(ValueError, match="claim_delta_noop_reason is required"):
        validate_adjudication_proposal(proposal)


def test_adjudication_pair_rejects_stale_design_or_wrong_authority() -> None:
    proposal = validate_adjudication_proposal({
        "schema_version": 1,
        "proposal_id": "adjudication-pair",
        "contract_hash": "1" * 64,
        "trial_plan_hash": "2" * 64,
        "methodology_hash": "3" * 64,
        "evidence_refs": ["evidence:pair"],
        "claim_evidence_delta": [],
        "claim_delta_noop_reason": "provenance is not empirical support",
        "obligation_delta": [{
            "obligation_id": "provenance-pair",
            "from_state": "absent",
            "to_state": "open",
            "criterion_ref": "methodology:provenance-repair",
        }],
        "decision_warrant": {
            "finding_refs": ["evidence:provenance-failure"],
            "rule_refs": ["methodology:provenance-required"],
            "inference_type": "semantic",
            "preregistered": False,
            "alternative_refs": [],
            "limitation_refs": ["limitation:untrusted-source"],
            "reentry_predicates": [],
            "required_authority": "independent_reviewer",
        },
    })
    decision = validate_adjudication_decision({
        "schema_version": 1,
        "decision_id": "decision-pair",
        "proposal_hash": proposal["proposal_hash"],
        "disposition": "accepted",
        "authority_class": "independent_reviewer",
        "authority_ref": "review:pair",
        "methodology_hash": "3" * 64,
    })

    with pytest.raises(ValueError, match="TrialPlan hash is stale"):
        validate_adjudication_pair(
            proposal,
            decision,
            expected_contract_hash="1" * 64,
            expected_trial_plan_hash="9" * 64,
            expected_methodology_hash="3" * 64,
        )

    wrong_authority = {
        **decision,
        "authority_class": "deterministic_verifier",
    }
    with pytest.raises(ValueError, match="authority does not satisfy"):
        validate_adjudication_pair(
            proposal,
            wrong_authority,
            expected_contract_hash="1" * 64,
            expected_trial_plan_hash="2" * 64,
            expected_methodology_hash="3" * 64,
        )


def test_decision_ready_closure_rejects_unresolved_blocking_obligations() -> None:
    proposal = {
        "schema_version": 1,
        "proposal_id": "exhaustion-17",
        "contract_hash": "1" * 64,
        "claim_projection_hash": "2" * 64,
        "obligation_projection_hash": "3" * 64,
        "graph_hash": "4" * 64,
        "methodology_hash": "5" * 64,
        "coverage_summary": {
            "declared_regions": 12,
            "attempted_regions": 12,
        },
        "blocking_obligations": [],
        "remaining_unknowns": [{
            "unknown_ref": "unknown:cross-market-transfer",
            "boundary": "outside permitted use",
        }],
        "attempted_trial_refs": ["trial:1", "trial:2"],
        "candidate_trial_frontier": [],
        "frontier_exclusions": [{
            "candidate_ref": "trial-candidate:3",
            "reason": "cannot change the bounded decision",
        }],
        "discovery_lens_refs": ["methodology:lens-set:1"],
        "reentry_predicates": [{
            "field": "scope.product_group",
            "operator": "changed",
        }],
        "disposition": "decision_ready",
        "closure_challenge_required": True,
    }

    assert validate_search_exhaustion_proposal(
        proposal
    )["disposition"] == "decision_ready"

    proposal["blocking_obligations"] = ["obligation:unresolved"]
    with pytest.raises(
        ValueError,
        match="decision_ready cannot retain blocking obligations",
    ):
        validate_search_exhaustion_proposal(proposal)


def test_methodology_change_is_semantic_and_rejects_skill_identity() -> None:
    proposal = {
        "schema_version": 1,
        "proposal_id": "methodology-17",
        "current_descriptor_hash": "1" * 64,
        "proposed_descriptor_hash": "2" * 64,
        "semantic_diff": {
            "added_discovery_lens": "delivery-window discontinuity"
        },
        "evidence_refs": ["evidence:repeated-omission"],
        "counterexample_refs": ["counterexample:thin-market"],
        "validation_refs": ["validation:17"],
        "failed_case_refs": [],
        "affected_contract_predicate": {
            "scope.product_group": {"eq": "CN_FUTURES"}
        },
        "expected_cost": {
            "context_bytes": 500,
            "reviewers": 1,
        },
        "compatibility": "semantic_change",
        "rollback_descriptor_hash": "1" * 64,
        "implementation_validation_refs": ["opaque-local-validation:17"],
    }

    assert validate_methodology_change_proposal(
        proposal
    )["compatibility"] == "semantic_change"

    proposal["skill_name"] = "research-obligation-cycle"
    with pytest.raises(
        ValueError,
        match="may persist descriptions, not Skill identity",
    ):
        validate_methodology_change_proposal(proposal)
