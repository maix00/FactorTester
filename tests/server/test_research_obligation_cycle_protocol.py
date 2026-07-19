from __future__ import annotations

import pytest

from server.services.research_graph.research_cycle.adjudication import (
    validate_adjudication_pair,
    validate_adjudication_decision,
    validate_adjudication_proposal,
)
from server.services.research_graph.research_cycle.authority import (
    validate_live_event_authorities,
)
from server.services.research_graph.research_cycle.contracts import (
    validate_decision_contract,
    validate_research_claim,
)
from server.services.research_graph.research_cycle.closure import (
    validate_search_exhaustion_decision,
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
    build_methodology_impact_plan,
    validate_methodology_change_proposal,
)


class _AuthorityStore:
    def __init__(self, rows: dict[str, dict]) -> None:
        self.rows = rows
        self.calls = 0

    def load_invocations(
        self,
        *,
        owner_user_id: str,
        invocation_ids: list[str],
    ) -> dict[str, dict]:
        self.calls += 1
        return {
            invocation_id: self.rows[invocation_id]
            for invocation_id in invocation_ids
            if invocation_id in self.rows
            and self.rows[invocation_id]["owner_user_id"] == owner_user_id
        }


def _invocation(
    invocation_id: str,
    *,
    role: str,
    principal: str,
    lineage: str,
    task_ref: str = "",
    status: str = "settled",
) -> dict:
    return {
        "invocation_id": invocation_id,
        "owner_user_id": "alice",
        "status": status,
        "actor_role": role,
        "authority_scope": "local_research",
        "agent_principal_hash": principal,
        "lineage_hash": lineage,
        "task_ref": task_ref,
    }


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
    with pytest.raises(
        ValueError,
        match="job_attempt evidence requires identity_refs.run_spec_hash",
    ):
        validate_agent_evidence_envelope({
            **envelope,
            "identity_refs": {
                key: value
                for key, value in envelope["identity_refs"].items()
                if key != "run_spec_hash"
            },
        })


def test_research_evidence_identity_requirements_are_kind_specific() -> None:
    semantic = {
        "schema_version": 2,
        "envelope_id": "factor-semantics-1",
        "evidence_kind": "factor_semantics",
        "source_refs": ["factor-workspace:revision-1"],
        "identity_refs": {
            "contract_hash": "1" * 64,
            "methodology_hash": "2" * 64,
        },
        "metric_refs": [],
        "artifact_refs": ["artifact:factor-ast-1"],
        "hypotheses_tested": 0,
        "stop_condition": None,
        "limitations": [],
        "conflicts": [],
    }

    assert validate_agent_evidence_envelope(semantic)["envelope_hash"]
    with pytest.raises(
        ValueError,
        match="factor_semantics evidence requires identity_refs.contract_hash",
    ):
        validate_agent_evidence_envelope({
            **semantic,
            "identity_refs": {"methodology_hash": "2" * 64},
        })
    with pytest.raises(ValueError, match="unsupported research evidence_kind"):
        validate_agent_evidence_envelope({
            **semantic,
            "evidence_kind": "analysis",
        })
    with pytest.raises(ValueError, match="unsupported research evidence_kind"):
        validate_agent_evidence_envelope({
            **semantic,
            "evidence_kind": "control_command",
            "identity_refs": {},
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


def test_live_independent_authority_is_batched_and_bound() -> None:
    proposal = validate_adjudication_proposal({
        "schema_version": 1,
        "proposal_id": "authority-pair",
        "proposer_invocation_id": "proposal-invocation",
        "contract_hash": "1" * 64,
        "trial_plan_hash": "2" * 64,
        "methodology_hash": "3" * 64,
        "evidence_refs": ["evidence:authority"],
        "claim_evidence_delta": [],
        "claim_delta_noop_reason": "authority test has no empirical delta",
        "obligation_delta": [{
            "obligation_id": "authority-obligation",
            "from_state": "absent",
            "to_state": "open",
            "criterion_ref": "methodology:authority",
        }],
        "decision_warrant": {
            "finding_refs": ["evidence:authority"],
            "rule_refs": ["methodology:authority"],
            "inference_type": "semantic",
            "preregistered": False,
            "alternative_refs": [],
            "limitation_refs": [],
            "reentry_predicates": [],
            "required_authority": "independent_reviewer",
        },
    })
    task_ref = (
        "research-cycle-adjudication:" + proposal["proposal_hash"]
    )
    decision = validate_adjudication_decision({
        "schema_version": 1,
        "decision_id": "authority-decision",
        "proposal_hash": proposal["proposal_hash"],
        "disposition": "accepted",
        "authority_class": "independent_reviewer",
        "authority_ref": "review-invocation",
        "methodology_hash": "3" * 64,
    })
    rows = {
        "proposal-invocation": _invocation(
            "proposal-invocation",
            role="researcher",
            principal="a" * 64,
            lineage="b" * 64,
        ),
        "review-invocation": _invocation(
            "review-invocation",
            role="reviewer",
            principal="c" * 64,
            lineage="d" * 64,
            task_ref=task_ref,
        ),
    }
    store = _AuthorityStore(rows)
    events = [
        {"event_type": "adjudication_proposed", "proposal": proposal},
        {"event_type": "adjudication_decided", "decision": decision},
    ]

    validate_live_event_authorities(
        owner_user_id="alice",
        events=events,
        pending_adjudications=[],
        pending_closure=None,
        transition_invocation_ids=[
            "proposal-invocation",
            "review-invocation",
        ],
        store=store,
    )

    assert store.calls == 1

    for field, value, message in (
        ("status", "reserved", "must be settled"),
        ("actor_role", "researcher", "invalid role"),
        ("task_ref", "research-cycle-adjudication:" + "9" * 64, "not bound"),
        ("agent_principal_hash", "a" * 64, "must differ"),
        ("lineage_hash", "b" * 64, "must differ"),
    ):
        invalid_rows = {
            key: dict(row) for key, row in rows.items()
        }
        invalid_rows["review-invocation"][field] = value
        with pytest.raises(ValueError, match=message):
            validate_live_event_authorities(
                owner_user_id="alice",
                events=events,
                pending_adjudications=[],
                pending_closure=None,
                transition_invocation_ids=[
                    "proposal-invocation",
                    "review-invocation",
                ],
                store=_AuthorityStore(invalid_rows),
            )

    with pytest.raises(ValueError, match="not found"):
        validate_live_event_authorities(
            owner_user_id="alice",
            events=events,
            pending_adjudications=[],
            pending_closure=None,
            transition_invocation_ids=[
                "proposal-invocation",
                "review-invocation",
            ],
            store=_AuthorityStore({
                "proposal-invocation": rows["proposal-invocation"],
            }),
        )


def test_routine_research_cycle_event_does_not_read_authority_store() -> None:
    store = _AuthorityStore({})

    validate_live_event_authorities(
        owner_user_id="alice",
        events=[{
            "event_type": "trial_plan_bound",
            "from_hash": "1" * 64,
            "to_hash": "2" * 64,
        }],
        pending_adjudications=[],
        pending_closure=None,
        transition_invocation_ids=[],
        store=store,
    )

    assert store.calls == 0


def test_live_closure_challenge_uses_bound_independent_invocation() -> None:
    proposal = validate_search_exhaustion_proposal({
        "schema_version": 1,
        "proposal_id": "closure-authority",
        "proposer_invocation_id": "closure-proposer",
        "contract_hash": "1" * 64,
        "claim_projection_hash": "2" * 64,
        "obligation_projection_hash": "3" * 64,
        "graph_hash": "4" * 64,
        "methodology_hash": "5" * 64,
        "coverage_summary": {
            "declared_scope_assessed": True,
            "stopping_rules_assessed": True,
            "frontier_assessed": True,
        },
        "blocking_obligations": [],
        "remaining_unknowns": [],
        "attempted_trial_refs": ["trial:closure"],
        "candidate_trial_frontier": [],
        "frontier_exclusions": [],
        "discovery_lens_refs": ["methodology:first-principles"],
        "reentry_predicates": [{"field": "methodology_hash"}],
        "disposition": "decision_ready",
        "closure_challenge_required": True,
    })
    decision = validate_search_exhaustion_decision({
        "schema_version": 1,
        "decision_id": "closure-authority-decision",
        "proposal_hash": proposal["proposal_hash"],
        "disposition": "accepted",
        "authority_class": "independent_reviewer",
        "authority_ref": "closure-reviewer",
        "methodology_hash": "5" * 64,
    })
    rows = {
        "closure-proposer": _invocation(
            "closure-proposer",
            role="researcher",
            principal="a" * 64,
            lineage="b" * 64,
        ),
        "closure-reviewer": _invocation(
            "closure-reviewer",
            role="reviewer",
            principal="c" * 64,
            lineage="d" * 64,
            task_ref=(
                "research-cycle-closure:" + proposal["proposal_hash"]
            ),
        ),
    }
    store = _AuthorityStore(rows)

    validate_live_event_authorities(
        owner_user_id="alice",
        events=[
            {"event_type": "closure_proposed", "proposal": proposal},
            {"event_type": "closure_decided", "decision": decision},
        ],
        pending_adjudications=[],
        pending_closure=None,
        transition_invocation_ids=[
            "closure-proposer",
            "closure-reviewer",
        ],
        store=store,
    )

    assert store.calls == 1
    with pytest.raises(ValueError, match="missing from agent_invocation_ids"):
        validate_live_event_authorities(
            owner_user_id="alice",
            events=[
                {"event_type": "closure_proposed", "proposal": proposal},
                {"event_type": "closure_decided", "decision": decision},
            ],
            pending_adjudications=[],
            pending_closure=None,
            transition_invocation_ids=["closure-proposer"],
            store=_AuthorityStore(rows),
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
            "declared_scope_assessed": True,
            "stopping_rules_assessed": True,
            "frontier_assessed": True,
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

    no_idea = {
        **proposal,
        "proposal_id": "exhaustion-no-idea",
        "coverage_summary": {
            "declared_scope_assessed": False,
            "stopping_rules_assessed": False,
            "frontier_assessed": False,
            "reason": "no idea",
        },
    }
    with pytest.raises(ValueError, match="requires assessed scope"):
        validate_search_exhaustion_proposal(no_idea)

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
            "all": [
                {
                    "field": "scope.product_group",
                    "equals": "CN_FUTURES",
                },
                {
                    "field": "factor.uses_continuous_contract",
                    "equals": True,
                },
            ],
        },
        "expected_cost": {
            "context_bytes": 500,
            "reviewers": 1,
        },
        "compatibility": "semantic_change",
        "rollback_descriptor_hash": "1" * 64,
        "implementation_validation_refs": ["opaque-local-validation:17"],
    }

    validated = validate_methodology_change_proposal(proposal)
    assert validated["compatibility"] == "semantic_change"
    same_review = validate_methodology_change_proposal({
        **proposal,
        "proposal_id": "methodology-18",
    })
    changed_review = validate_methodology_change_proposal({
        **proposal,
        "affected_contract_predicate": {
            "field": "scope.product_group",
            "equals": "EQUITIES",
        },
    })
    assert same_review["review_input_hash"] == validated["review_input_hash"]
    assert changed_review["review_input_hash"] != validated[
        "review_input_hash"
    ]
    impact = build_methodology_impact_plan(validated, [
        {
            "contract_ref": "contract:trend-cn",
            "scope": {"product_group": "CN_FUTURES"},
            "factor": {"uses_continuous_contract": True},
        },
        {
            "contract_ref": "contract:equity",
            "scope": {"product_group": "EQUITIES"},
            "factor": {"uses_continuous_contract": False},
        },
        {
            "contract_ref": "contract:unknown",
            "scope": {"product_group": "CN_FUTURES"},
            "factor": {},
        },
    ])
    assert impact["affected_contract_refs"] == ["contract:trend-cn"]
    assert impact["unaffected_contract_refs"] == ["contract:equity"]
    assert impact["undetermined_contract_refs"] == ["contract:unknown"]
    assert impact["proposed_reopen_refs"] == ["contract:trend-cn"]
    assert impact["unaffected_branches_and_jobs_action"] == "continue"

    proposal["skill_name"] = "research-obligation-cycle"
    with pytest.raises(
        ValueError,
        match="may persist descriptions, not Skill identity",
    ):
        validate_methodology_change_proposal(proposal)
