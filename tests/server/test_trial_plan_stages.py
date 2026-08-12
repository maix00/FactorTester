"""TrialPlan stage transition integration tests."""

from __future__ import annotations

from copy import deepcopy
import hashlib

import orjson
import settings as Settings
from server.services import agent_flow
from server.services.research_graph.branch.transition import (
    advance_graph_branch,
)
from server.services.research_graph.branch.next_packet import (
    build_graph_branch_next,
)
from server.services.research_graph.research_cycle.adjudication import (
    validate_adjudication_decision,
    validate_adjudication_proposal,
)
from server.services.research_graph.research_cycle.replay import (
    validate_research_cycle_checkpoint,
)
from server.services.research_graph.trial_plan import (
    canonical_trial_plan,
    trial_plan_hash,
)
from tests.server.trial_plan_fixtures import (
    initialize_branch,
    initialize_graph_version,
    trial_plan_v4,
)
from tests.server.test_trial_plan_contract_v5 import trial_plan_v5
from tools.data.sqlite.db import connect_sqlite


def test_accepting_initial_v5_plan_atomically_initializes_action_checkpoint(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "v5-initial-checkpoint.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    plan = canonical_trial_plan(trial_plan_v5())
    plan_hash = trial_plan_hash(plan)
    initialize_branch(path, "")
    initialize_graph_version(path)
    obligations = [
        {
            "schema_version": 1,
            "obligation_id": obligation_id,
            "contract_hash": "3" * 64,
                "claim_ids": ["claim-v5"],
                "obligation_kind": "trial_execution",
                "title_zh": "冻结试验执行",
                "epistemic_question": "Can the frozen Evidence Action be executed?",
            "scope": {"stage": "validation"},
            "discharge_criterion": {"rule_ref": "trial-plan:v5"},
            "status": "open",
            "materiality": "decision_blocking",
            "methodology_hash": "4" * 64,
            "created_event_ref": "trace:preregister-v5",
        }
        for obligation_id in ("obligation:primary", "obligation:secondary")
    ]
    checkpoint = validate_research_cycle_checkpoint({
        "schema_version": 1,
        "contract_hash": "3" * 64,
        "trial_plan_hash": plan_hash,
        "methodology_hash": "4" * 64,
        "claims": [{
            "schema_version": 1,
            "claim_id": "claim-v5",
            "contract_hash": "3" * 64,
            "claim_ref": "factor-claim:v5",
            "claim_type": "bounded_predictive_relationship",
            "scope": {"stage": "validation"},
            "evidence_state": "unknown",
            "evidence_refs": [],
        }],
        "obligations": obligations,
        "pending_adjudications": [],
        "pending_closure": None,
    })

    advance_graph_branch(
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

    with connect_sqlite(path) as conn:
        row = conn.execute(
            "SELECT current_trial_plan_hash, trial_stage_projection_json "
            "FROM research_graph_branches WHERE branch_id='branch-1'"
        ).fetchone()
    projection = orjson.loads(row["trial_stage_projection_json"])
    assert row["current_trial_plan_hash"] == plan_hash
    assert projection["schema_version"] == 3
    assert projection["current_action_id"] == "action:ic"
    assert projection["current_action_status"] == "unreleased"
    assert projection["execution_node"] == "diagnostics"


def test_branch_persists_stage_advance_then_binds_child_plan(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "stages.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    monkeypatch.setenv(
        "AGENT_FLOW_DB_PATH",
        str(tmp_path / "agent-flow.sqlite"),
    )
    agent_flow.clear_store_cache()
    plan = canonical_trial_plan(trial_plan_v4())
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
            "claim_id": "claim-stage",
            "contract_hash": "1" * 64,
            "claim_ref": "factor-claim:stage",
            "claim_type": "bounded_predictive_relationship",
            "scope": {"sample": "selection"},
            "evidence_state": "unknown",
            "evidence_refs": [],
        }],
        "obligations": [{
            "schema_version": 1,
            "obligation_id": "obligation-stage",
            "contract_hash": "1" * 64,
                "claim_ids": ["claim-stage"],
                "obligation_kind": "transfer_boundary_support",
                "title_zh": "迁移边界支持",
                "epistemic_question": (
                "Does the preregistered selection evidence justify "
                "testing the Claim on the declared transfer boundary?"
            ),
            "scope": {"sample": "selection"},
            "discharge_criterion": {"rule_ref": "selection:advance"},
            "status": "open",
            "materiality": "decision_blocking",
            "methodology_hash": "2" * 64,
            "created_event_ref": "trace:init-stage",
        }],
        "pending_adjudications": [],
        "pending_closure": None,
    })
    advance_graph_branch(
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
    with connect_sqlite(path) as conn:
        frozen = conn.execute(
            """
            SELECT latest_trace_id, trial_stage_projection_json
            FROM research_graph_branches WHERE branch_id='branch-1'
            """
        ).fetchone()
    projection = orjson.loads(frozen["trial_stage_projection_json"])
    assert projection["current_stage"] == "selection"
    packet = build_graph_branch_next(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
    )
    assert packet["candidate_trial_frontier"]["trial_stage"] == {
        "plan_version": 1,
        "current_stage": "selection",
        "next_stage": "validation",
        "partition_commitment_hash": projection[
            "partition_commitment_hash"
        ],
    }
    assert packet["next_bytes"] <= 6000

    store = agent_flow.get_store()
    invocation = store.reserve_invocation(
        owner_user_id="alice",
        agent_id="research:stage",
        actor_role="researcher",
        authority_scope="local_research",
        purpose="adjudicate selection stage",
        runtime_id="pytest",
        model_id="test-model",
        max_input_tokens=10,
        max_output_tokens=10,
        agent_principal_hash=hashlib.sha256(b"stage-agent").hexdigest(),
        lineage_hash=hashlib.sha256(b"stage-lineage").hexdigest(),
    )
    store.settle_invocation(
        owner_user_id="alice",
        invocation_id=invocation["invocation_id"],
        input_tokens=1,
        output_tokens=1,
        provider_request_id="stage-advance",
    )
    proposal = validate_adjudication_proposal({
        "schema_version": 2,
        "proposal_id": "proposal-stage-advance",
        "proposer_invocation_id": invocation["invocation_id"],
        "contract_hash": checkpoint["contract_hash"],
        "trial_plan_hash": plan_hash,
        "methodology_hash": checkpoint["methodology_hash"],
        "evidence_refs": ["evidence:selection"],
        "claim_evidence_delta": [{
            "claim_id": "claim-stage",
            "from_state": "unknown",
            "to_state": "inconclusive",
            "evidence_grade": "exploratory",
            "scope": {"sample": "selection"},
        }],
        "obligation_delta": [{
            "obligation_id": "obligation-stage",
            "from_state": "open",
            "to_state": "serviced",
            "criterion_ref": "selection:advance",
        }],
        "recommended_action": "advance_trial_stage",
        "decision_warrant": {
            "finding_refs": ["evidence:selection"],
            "rule_refs": ["selection:advance"],
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
        "decision_id": "decision-stage-advance",
        "proposal_hash": proposal["proposal_hash"],
        "disposition": "accepted",
        "authority_class": "preregistered_rule",
        "authority_ref": "selection:advance",
        "methodology_hash": checkpoint["methodology_hash"],
    })
    advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="advance-stage",
        evidence={
            "agent_invocation_ids": [invocation["invocation_id"]],
            "research_cycle": {
                "schema_version": 1,
                "parent_trace_ref": f"trace:{frozen['latest_trace_id']}",
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
    with connect_sqlite(path) as conn:
        advanced = conn.execute(
            """
            SELECT latest_trace_id, trial_stage_projection_json
            FROM research_graph_branches WHERE branch_id='branch-1'
            """
        ).fetchone()
        advanced_trace = conn.execute(
            "SELECT evidence_json FROM research_graph_trace WHERE trace_id=?",
            (advanced["latest_trace_id"],),
        ).fetchone()
    advanced_projection = orjson.loads(
        advanced["trial_stage_projection_json"]
    )
    cycle = orjson.loads(
        advanced_trace["evidence_json"]
    )["research_cycle_checkpoint"]
    assert advanced_projection["current_stage"] == "validation"
    assert advanced_projection["completed_mask"] == 1

    child = deepcopy(plan)
    child["version"] = 2
    child["parent_trial_plan_hash"] = plan_hash
    child_hash = trial_plan_hash(child)
    advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="freeze-plan",
        evidence={
            "trial_plan": child,
            "research_cycle": {
                "schema_version": 1,
                "parent_trace_ref": f"trace:{advanced['latest_trace_id']}",
                "expected_base_hash": cycle["projection_hash"],
                "events": [{
                    "event_type": "trial_plan_bound",
                    "from_hash": plan_hash,
                    "to_hash": child_hash,
                }],
            },
        },
    )
    with connect_sqlite(path) as conn:
        child_row = conn.execute(
            """
            SELECT current_trial_plan_hash, trial_stage_projection_json
            FROM research_graph_branches WHERE branch_id='branch-1'
            """
        ).fetchone()
    child_projection = orjson.loads(
        child_row["trial_stage_projection_json"]
    )
    assert child_row["current_trial_plan_hash"] == child_hash
    assert child_projection["plan_version"] == 2
    assert child_projection["current_stage"] == "validation"
