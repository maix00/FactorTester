"""Factor revision opens a new TrialPlan lineage without rewriting history."""

from __future__ import annotations

import orjson
import pytest

import settings as Settings
from server.services.research_graph.branch.transition import (
    advance_graph_branch,
)
from server.services.research_graph.research_cycle.replay import (
    validate_research_cycle_checkpoint,
)
from server.services.research_graph.trial_plan import (
    canonical_trial_plan,
    project_trial_plan_stage,
    trial_plan_hash,
)
from tests.server.trial_plan_fixtures import (
    initialize_branch,
    initialize_graph_version,
    trial_plan_v4,
)
from tools.data.sqlite.db import connect_sqlite


def _checkpoint(plan_hash: str) -> dict:
    return validate_research_cycle_checkpoint({
        "schema_version": 1,
        "contract_hash": "1" * 64,
        "trial_plan_hash": plan_hash,
        "methodology_hash": "2" * 64,
        "claims": [{
            "schema_version": 1,
            "claim_id": "claim-factor-revision",
            "contract_hash": "1" * 64,
            "claim_ref": "factor-claim:revision",
            "claim_type": "bounded_predictive_relationship",
            "scope": {"product_group": "CNFutures"},
            "evidence_state": "inconclusive",
            "evidence_refs": ["evidence:old-plan"],
        }],
        "obligations": [{
            "schema_version": 1,
            "obligation_id": "obligation-stage",
            "contract_hash": "1" * 64,
            "claim_ids": ["claim-factor-revision"],
            "obligation_kind": "mechanism_revision",
            "epistemic_question": "Can a revised factor mechanism help?",
            "scope": {"product_group": "CNFutures"},
            "discharge_criterion": {"rule_ref": "revision:test"},
            "status": "open",
            "materiality": "decision_blocking",
            "methodology_hash": "2" * 64,
            "created_event_ref": "trace:old-plan",
        }],
        "pending_adjudications": [],
        "pending_closure": None,
    })


def _seed_factor_improvement(
    path,
    *,
    plan: dict,
    checkpoint: dict,
) -> None:
    plan_hash = trial_plan_hash(plan)
    projection = project_trial_plan_stage(
        trial_plan=plan,
        trial_plan_hash=plan_hash,
        current_trial_plan_hash="",
        current_projection={},
        execution_node="result_audit",
    )
    evidence = {
        "research_cycle_checkpoint": checkpoint,
        "evidence_refs": ["evidence:old-plan"],
    }
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id,
                from_node, to_node, evidence_json, telemetry_json,
                actor, created_at
            ) VALUES (
                'trace-old-plan', 'instance-1', 'branch-1',
                'authorized-revision', 'result_audit',
                'factor_improvement', ?, '{}', 'alice', 1
            )
            """,
            (orjson.dumps(evidence).decode(),),
        )
        conn.execute(
            """
            UPDATE research_graph_branches
            SET current_node='factor_improvement',
                latest_trace_id='trace-old-plan',
                trial_stage_projection_json=?
            WHERE branch_id='branch-1'
            """,
            (orjson.dumps(projection).decode(),),
        )


def _revision_facts() -> dict:
    return {
        "new_hypothesis_version_recorded": True,
        "trial_ledger_incremented": True,
        "holdout_status_recorded": True,
        "factor_change_retained": True,
    }


def test_factor_revision_releases_plan_then_accepts_new_v1_lineage(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "factor-revision.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    old_plan = canonical_trial_plan(trial_plan_v4())
    old_hash = trial_plan_hash(old_plan)
    initialize_branch(path, old_hash)
    initialize_graph_version(path)
    checkpoint = _checkpoint(old_hash)
    _seed_factor_improvement(
        path,
        plan=old_plan,
        checkpoint=checkpoint,
    )

    with pytest.raises(ValueError, match="release the old TrialPlan"):
        advance_graph_branch(
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            edge_id="start-new-hypothesis",
            evidence={
                **_revision_facts(),
                "trial_plan": old_plan,
            },
        )

    advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="start-new-hypothesis",
        evidence=_revision_facts(),
    )
    with connect_sqlite(path) as conn:
        released = conn.execute(
            """
            SELECT current_trial_plan_hash, trial_stage_projection_json,
                   latest_trace_id
            FROM research_graph_branches WHERE branch_id='branch-1'
            """
        ).fetchone()
        old_trace = conn.execute(
            """
            SELECT evidence_json FROM research_graph_trace
            WHERE trace_id='trace-old-plan'
            """
        ).fetchone()
        release_trace = conn.execute(
            """
            SELECT evidence_json FROM research_graph_trace
            WHERE trace_id=?
            """,
            (released["latest_trace_id"],),
        ).fetchone()
    assert released["current_trial_plan_hash"] == ""
    assert orjson.loads(released["trial_stage_projection_json"]) == {}
    assert orjson.loads(old_trace["evidence_json"])[
        "research_cycle_checkpoint"
    ]["trial_plan_hash"] == old_hash
    released_cycle = orjson.loads(release_trace["evidence_json"])[
        "research_cycle_checkpoint"
    ]
    assert released_cycle["trial_plan_hash"] == ""

    advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="hypothesis-to-validation",
        evidence={},
    )
    with connect_sqlite(path) as conn:
        hypothesis_row = conn.execute(
            """
            SELECT latest_trace_id FROM research_graph_branches
            WHERE branch_id='branch-1'
            """
        ).fetchone()
        hypothesis_trace = conn.execute(
            """
            SELECT evidence_json FROM research_graph_trace
            WHERE trace_id=?
            """,
            (hypothesis_row["latest_trace_id"],),
        ).fetchone()
    hypothesis_cycle = orjson.loads(hypothesis_trace["evidence_json"])[
        "research_cycle_checkpoint"
    ]

    new_plan = trial_plan_v4()
    new_plan["trial_plan_id"] = "plan-new-hypothesis"
    new_plan["hypothesis_ref"] = "hypothesis:factor-revision-v2"
    new_plan = canonical_trial_plan(new_plan)
    new_hash = trial_plan_hash(new_plan)
    advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="freeze-plan",
        evidence={
            "trial_plan": new_plan,
            "research_cycle": {
                "schema_version": 1,
                "parent_trace_ref": (
                    f"trace:{hypothesis_row['latest_trace_id']}"
                ),
                "expected_base_hash": hypothesis_cycle["projection_hash"],
                "events": [{
                    "event_type": "trial_plan_bound",
                    "from_hash": "",
                    "to_hash": new_hash,
                }],
            },
        },
    )
    with connect_sqlite(path) as conn:
        rebound = conn.execute(
            """
            SELECT current_trial_plan_hash, trial_stage_projection_json
            FROM research_graph_branches WHERE branch_id='branch-1'
            """
        ).fetchone()
    projection = orjson.loads(rebound["trial_stage_projection_json"])
    assert rebound["current_trial_plan_hash"] == new_hash
    assert projection["trial_plan_id"] == "plan-new-hypothesis"
    assert projection["plan_version"] == 1
