"""TrialPlan schema, hash, and graph-trace freeze tests."""

from __future__ import annotations

import hashlib

import orjson
import pytest

import settings as Settings
from server.services import agent_flow
from server.services.research_graph.branch.transition import (
    advance_graph_branch,
)
from server.services.research_graph.trial_plan import (
    canonical_trial_plan,
    prepare_trial_plan_evidence,
    trial_plan_hash,
    validate_trial_plan_transition,
)
from server.services.research_graph.research_cycle.replay import (
    validate_research_cycle_checkpoint,
)
from server.services.research_graph.research_cycle.adjudication import (
    validate_adjudication_decision,
    validate_adjudication_proposal,
)
from tests.server.trial_plan_fixtures import (
    initialize_branch,
    initialize_graph_version,
    trial_plan,
)
from tools.data.sqlite.db import connect_sqlite


def test_trial_plan_hash_is_canonical_and_source_free() -> None:
    plan = trial_plan("a" * 64)
    reordered = dict(reversed(list(plan.items())))

    assert canonical_trial_plan(reordered) == canonical_trial_plan(plan)
    assert trial_plan_hash(reordered) == trial_plan_hash(plan)
    with pytest.raises(ValueError, match="unsupported fields"):
        canonical_trial_plan({**plan, "factor_source": "secret.py"})
    private_path = {
        **plan,
        "stopping": {
            **plan["stopping"],
            "parameters": {"rationale_path": "/Users/alice/private.md"},
        },
    }
    with pytest.raises(ValueError, match="private local path"):
        canonical_trial_plan(private_path)
    hidden_source = {
        **plan,
        "stopping": {
            **plan["stopping"],
            "parameters": {"formula": "private factor expression"},
        },
    }
    with pytest.raises(ValueError, match="private/source fields"):
        canonical_trial_plan(hidden_source)


def test_trial_plan_rejects_sample_stopping_and_runspec_mismatches() -> None:
    plan = trial_plan("a" * 64)
    cross_role = {
        **plan,
        "sample_roles": [
            *plan["sample_roles"],
            {
                "sample_ref": "holdout-2024",
                "sample_hash": "d" * 64,
                "role": "holdout",
                "run_spec_hashes": ["a" * 64],
            },
        ],
    }
    with pytest.raises(ValueError, match="cannot cross TrialPlan sample roles"):
        canonical_trial_plan(cross_role)
    distinct_slice = {
        **cross_role["sample_roles"][1],
        "sample_hash": "e" * 64,
    }
    canonical_trial_plan({
        **plan,
        "sample_roles": [*plan["sample_roles"], distinct_slice],
    })
    unknown_outcome = {
        **plan,
        "stopping": {
            **plan["stopping"],
            "monitored_outcomes": ["unplanned-sharpe"],
        },
    }
    with pytest.raises(ValueError, match="undeclared outcomes"):
        canonical_trial_plan(unknown_outcome)
    unplanned_run = {
        **plan,
        "comparisons": [{
            "comparison_id": "main-comparison",
            "members": [{
                "run_spec_hash": "b" * 64,
                "trial_role": "main-only",
            }],
        }],
    }
    with pytest.raises(ValueError, match="no declared sample role"):
        canonical_trial_plan(unplanned_run)


def test_transition_freezes_one_body_then_accepts_only_matching_hash() -> None:
    plan = trial_plan("a" * 64)
    prepared, plan_hash, has_body = prepare_trial_plan_evidence({
        "trial_plan": plan,
    })

    assert prepared["trial_plan_hash"] == plan_hash == trial_plan_hash(plan)
    assert validate_trial_plan_transition(
        current_hash="",
        proposed_hash=plan_hash,
        has_body=has_body,
    ) == plan_hash
    assert validate_trial_plan_transition(
        current_hash=plan_hash,
        proposed_hash=plan_hash,
        has_body=False,
    ) == plan_hash
    with pytest.raises(ValueError, match="already persisted"):
        validate_trial_plan_transition(
            current_hash=plan_hash,
            proposed_hash=plan_hash,
            has_body=True,
        )
    with pytest.raises(ValueError, match="new immutable body"):
        validate_trial_plan_transition(
            current_hash=plan_hash,
            proposed_hash="b" * 64,
            has_body=False,
        )


def test_graph_transition_persists_one_canonical_plan_body(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "transition.sqlite"
    agent_flow_path = tmp_path / "agent-flow.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    monkeypatch.setenv("AGENT_FLOW_DB_PATH", str(agent_flow_path))
    agent_flow.clear_store_cache()
    plan = trial_plan("a" * 64)
    plan_hash = trial_plan_hash(plan)
    initialize_branch(path, "")
    initialize_graph_version(path)
    checkpoint = validate_research_cycle_checkpoint({
        "schema_version": 1,
        "contract_hash": "1" * 64,
        "trial_plan_hash": plan_hash,
        "methodology_hash": "2" * 64,
        "claims": [{
            "schema_version": 1,
            "claim_id": "claim-plan",
            "contract_hash": "1" * 64,
            "claim_ref": "factor-claim:plan",
            "claim_type": "bounded_predictive_relationship",
            "scope": {"sample": "confirmatory"},
            "evidence_state": "unknown",
            "evidence_refs": [],
        }],
        "obligations": [{
            "schema_version": 1,
            "obligation_id": "obligation-plan",
            "contract_hash": "1" * 64,
            "claim_ids": ["claim-plan"],
            "obligation_kind": "preregistered_test",
            "epistemic_question": "Does the frozen test reject?",
            "scope": {"sample": "confirmatory"},
            "discharge_criterion": {"rule_ref": "trial-plan:reject"},
            "status": "open",
            "materiality": "decision_blocking",
            "methodology_hash": "2" * 64,
            "created_event_ref": "trace:init",
        }],
        "pending_adjudications": [],
        "pending_closure": None,
    })

    advanced = advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="freeze-plan",
        evidence={
            "trial_plan": plan,
            "research_cycle": {
                "schema_version": 1,
                "parent_trace_ref": "",
                "initial_checkpoint": checkpoint,
                "expected_base_hash": checkpoint["projection_hash"],
                "events": [],
            },
        },
    )

    assert advanced["current_node"] == "diagnostics"
    with connect_sqlite(path) as conn:
        branch = conn.execute(
            """
            SELECT current_trial_plan_hash
            FROM research_graph_branches
            WHERE branch_id='branch-1'
            """
        ).fetchone()
        trace = conn.execute(
            """
            SELECT trace_id, evidence_json FROM research_graph_trace
            WHERE branch_id='branch-1'
            """
        ).fetchone()
    evidence = orjson.loads(trace["evidence_json"])
    assert str(branch["current_trial_plan_hash"]) == plan_hash
    assert evidence["trial_plan"] == canonical_trial_plan(plan)
    assert evidence["trial_plan_hash"] == plan_hash
    assert evidence["research_cycle"]["bootstrap_checkpoint"] is True
    assert evidence["research_cycle_checkpoint"] == checkpoint

    store = agent_flow.get_store()
    invocation = store.reserve_invocation(
        owner_user_id="alice",
        agent_id="research:test",
        actor_role="researcher",
        authority_scope="local_research",
        purpose="propose preregistered adjudication",
        runtime_id="pytest",
        model_id="test-model",
        max_input_tokens=10,
        max_output_tokens=10,
        agent_principal_hash=hashlib.sha256(b"researcher").hexdigest(),
        lineage_hash=hashlib.sha256(b"research-lineage").hexdigest(),
    )
    store.settle_invocation(
        owner_user_id="alice",
        invocation_id=invocation["invocation_id"],
        input_tokens=1,
        output_tokens=1,
        provider_request_id="trial-plan-contract-proposal",
    )
    proposal = validate_adjudication_proposal({
        "schema_version": 1,
        "proposal_id": "proposal-plan",
        "proposer_invocation_id": invocation["invocation_id"],
        "contract_hash": checkpoint["contract_hash"],
        "trial_plan_hash": plan_hash,
        "methodology_hash": checkpoint["methodology_hash"],
        "evidence_refs": ["evidence:plan-result"],
        "claim_evidence_delta": [{
            "claim_id": "claim-plan",
            "from_state": "unknown",
            "to_state": "contradicted",
            "evidence_grade": "preregistered",
            "scope": {"sample": "confirmatory"},
        }],
        "obligation_delta": [{
            "obligation_id": "obligation-plan",
            "from_state": "open",
            "to_state": "discharged",
            "criterion_ref": "trial-plan:reject",
        }],
        "decision_warrant": {
            "finding_refs": ["evidence:plan-result"],
            "rule_refs": ["trial-plan:reject"],
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
        "decision_id": "decision-plan",
        "proposal_hash": proposal["proposal_hash"],
        "disposition": "accepted",
        "authority_class": "preregistered_rule",
        "authority_ref": "trial-plan:reject",
        "methodology_hash": checkpoint["methodology_hash"],
    })
    advanced = advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="adjudicate-result",
        evidence={
            "agent_invocation_ids": [invocation["invocation_id"]],
            "research_cycle": {
                "schema_version": 1,
                "parent_trace_ref": f"trace:{trace['trace_id']}",
                "expected_base_hash": checkpoint["projection_hash"],
                "events": [
                    {
                        "event_type": "adjudication_proposed",
                        "proposal": proposal,
                    },
                    {
                        "event_type": "adjudication_decided",
                        "decision": decision,
                    },
                ],
            },
        },
    )
    assert advanced["current_node"] == "result"
    with connect_sqlite(path) as conn:
        latest = conn.execute(
            """
            SELECT evidence_json FROM research_graph_trace
            WHERE trace_id=(
                SELECT latest_trace_id FROM research_graph_branches
                WHERE branch_id='branch-1'
            )
            """
        ).fetchone()
    projected = orjson.loads(
        latest["evidence_json"]
    )["research_cycle_checkpoint"]
    assert projected["claims"][0]["evidence_state"] == "contradicted"
    assert projected["obligations"][0]["status"] == "discharged"
