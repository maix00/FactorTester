"""Atomic persistence tests for the TrialPlan v5 execution checkpoint."""

from __future__ import annotations

import sqlite3

import orjson
import pytest

from server.services.research_graph.trial_plan import (
    ExecutionCheckpointConflictError,
    apply_execution_checkpoint_operation,
    audit_current_action,
    backfill_action_adjudication_receipt,
    ensure_action_adjudication_receipt_table,
    initial_execution_checkpoint,
    load_action_adjudication_receipt,
    transition_action_status,
    trial_plan_hash,
)
from server.services.research_graph.trial_plan.execution_checkpoint_contract import (
    seal_checkpoint,
    without_checkpoint_hash,
)
from server.services.research_graph.research_cycle.adjudication import (
    validate_adjudication_proposal,
)
from server.services.research_graph.work_packages import insert_active
from tests.server.test_trial_plan_contract_v5 import trial_plan_v5
from tests.server.trial_plan_fixtures import initialize_branch
from tools.data.sqlite.db import connect_sqlite


def _branch(path) -> tuple[dict, dict]:
    plan = trial_plan_v5()
    plan_hash = trial_plan_hash(plan)
    checkpoint = initial_execution_checkpoint(
        trial_plan=plan,
        expected_trial_plan_hash=plan_hash,
        execution_node="trial_execution",
    )
    initialize_branch(path, plan_hash)
    with connect_sqlite(path) as conn:
        insert_active(
            conn,
            owner="alice",
            work_package_id="instance-1",
            workspace_id="workspace-1",
            created_at=1,
        )
        conn.execute(
            """
            UPDATE research_graph_branches
            SET current_node='trial_execution', latest_trace_id='trace-1',
                trial_stage_projection_json=?
            WHERE branch_id='branch-1'
            """,
            (orjson.dumps(checkpoint).decode(),),
        )
    return plan, checkpoint


def test_checkpoint_compare_and_swap_persists_one_legal_step(tmp_path) -> None:
    path = tmp_path / "checkpoint.sqlite"
    plan, checkpoint = _branch(path)
    released = transition_action_status(checkpoint, target="released")

    with connect_sqlite(path) as conn:
        statements: list[str] = []
        conn.set_trace_callback(statements.append)
        stored = apply_execution_checkpoint_operation(
            conn,
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            trial_plan=plan,
            expected_latest_trace_id="trace-1",
            expected_checkpoint_hash=checkpoint["projection_hash"],
            operation="release",
        )
        conn.set_trace_callback(None)

    assert stored["checkpoint"] == released
    hot_path = [
        statement for statement in statements
        if statement.lstrip().upper().startswith(("SELECT", "UPDATE"))
    ]
    assert len(hot_path) == 2
    with connect_sqlite(path) as conn:
        row = conn.execute(
            "SELECT trial_stage_projection_json, latest_trace_id "
            "FROM research_graph_branches WHERE branch_id='branch-1'"
        ).fetchone()
    assert orjson.loads(row["trial_stage_projection_json"]) == released
    assert row["latest_trace_id"] == "trace-1"


def test_checkpoint_compare_and_swap_rejects_stale_or_skipped_state(tmp_path) -> None:
    path = tmp_path / "checkpoint-stale.sqlite"
    plan, checkpoint = _branch(path)
    released = transition_action_status(checkpoint, target="released")

    with connect_sqlite(path) as conn:
        with pytest.raises(ExecutionCheckpointConflictError, match="trace"):
            apply_execution_checkpoint_operation(
                conn,
                instance_id="instance-1",
                branch_id="branch-1",
                owner="alice",
                trial_plan=plan,
                expected_latest_trace_id="trace-stale",
                expected_checkpoint_hash=checkpoint["projection_hash"],
                operation="release",
            )
        with pytest.raises(ValueError, match="unreleased -> running"):
            apply_execution_checkpoint_operation(
                conn,
                instance_id="instance-1",
                branch_id="branch-1",
                owner="alice",
                trial_plan=plan,
                expected_latest_trace_id="trace-1",
                expected_checkpoint_hash=checkpoint["projection_hash"],
                operation="mark_running",
            )


def _admitted(checkpoint: dict) -> dict:
    checkpoint = transition_action_status(checkpoint, target="released")
    checkpoint = transition_action_status(
        checkpoint,
        target="evidence_ready",
        evidence_refs=["evidence:action-result"],
    )
    return transition_action_status(
        checkpoint,
        target="admitted",
        qualification="eligible",
    )


def _adjudication(plan: dict, checkpoint: dict) -> tuple[dict, dict]:
    proposal = validate_adjudication_proposal({
        "schema_version": 2,
        "proposal_id": "proposal-action-audit",
        "contract_hash": plan["decision_contract_hash"],
        "trial_plan_hash": trial_plan_hash(plan),
        "methodology_hash": plan["methodology_hash"],
        "evidence_refs": checkpoint["current_action_output_evidence_refs"],
        "claim_evidence_delta": [],
        "claim_delta_noop_reason": "No Claim is promoted.",
        "obligation_delta": [{
            "obligation_id": "obligation:primary",
            "from_state": "open",
            "to_state": "serviced",
            "criterion_ref": "criterion:action-result-reviewed",
        }],
        "recommended_action": "continue_execution",
        "decision_warrant": {
            "finding_refs": checkpoint["current_action_output_evidence_refs"],
            "rule_refs": ["rule:action-result-audit"],
            "inference_type": "deterministic",
            "preregistered": True,
            "alternative_refs": [],
            "limitation_refs": [],
            "reentry_predicates": [],
            "required_authority": "deterministic_verifier",
        },
    })
    decision = {
        "schema_version": 1,
        "decision_id": "decision-action-audit",
        "proposal_hash": proposal["proposal_hash"],
        "disposition": "accepted",
        "authority_class": "deterministic_verifier",
        "authority_ref": "verifier:result-audit",
        "methodology_hash": plan["methodology_hash"],
    }
    return proposal, decision


def test_audit_atomically_appends_and_loads_validated_receipt(tmp_path) -> None:
    path = tmp_path / "checkpoint-audit.sqlite"
    plan, initial = _branch(path)
    checkpoint = _admitted(initial)
    proposal, decision = _adjudication(plan, checkpoint)
    with connect_sqlite(path) as conn:
        conn.execute(
            "UPDATE research_graph_branches "
            "SET trial_stage_projection_json=? WHERE branch_id='branch-1'",
            (orjson.dumps(checkpoint).decode(),),
        )
        outcome = apply_execution_checkpoint_operation(
            conn,
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            trial_plan=plan,
            expected_latest_trace_id="trace-1",
            expected_checkpoint_hash=checkpoint["projection_hash"],
            operation="audit",
            payload={"proposal": proposal, "decision": decision},
        )
        receipt = load_action_adjudication_receipt(
            conn,
            "instance-1",
            "branch-1",
            trial_plan_hash(plan),
            "action:ic",
        )

    assert receipt == outcome["adjudication_receipt"]
    assert receipt["proposal"] == proposal
    assert receipt["decision"]["decision_id"] == "decision-action-audit"
    assert receipt["contract_hash"] == plan["decision_contract_hash"]
    assert receipt["methodology_hash"] == plan["methodology_hash"]
    assert receipt["evidence_refs"] == ["evidence:action-result"]
    with connect_sqlite(path) as conn:
        persisted = load_action_adjudication_receipt(
            conn, "instance-1", "branch-1",
            trial_plan_hash(plan), "action:ic",
        )
    assert persisted == receipt


def test_backfill_validates_checkpoint_binding_and_never_overwrites(tmp_path) -> None:
    path = tmp_path / "checkpoint-backfill.sqlite"
    plan, initial = _branch(path)
    checkpoint = _admitted(initial)
    proposal, decision = _adjudication(plan, checkpoint)
    with connect_sqlite(path) as conn:
        audited = apply_execution_checkpoint_operation(
            conn,
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            trial_plan=plan,
            expected_latest_trace_id="trace-1",
            expected_checkpoint_hash=initial["projection_hash"],
            operation="release",
        )
        # Backfill accepts historical checkpoint data, independent of the hot
        # branch cursor, but validates every semantic identity in the pair.
        historical = audit_current_action(
            checkpoint,
            trial_plan=plan,
            proposal=proposal,
            decision=decision,
        )
        ensure_action_adjudication_receipt_table(conn)
        backfill_action_adjudication_receipt(
            conn,
            instance_id="instance-1",
            branch_id="branch-historical",
            trial_plan=plan,
            checkpoint=historical,
            proposal=proposal,
            decision=decision,
        )
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            backfill_action_adjudication_receipt(
                conn,
                instance_id="instance-1",
                branch_id="branch-historical",
                trial_plan=plan,
                checkpoint=historical,
                proposal=proposal,
                decision=decision,
            )

    assert audited["checkpoint"]["current_action_status"] == "released"


def test_backfill_rejects_audit_ref_decision_mismatch(tmp_path) -> None:
    path = tmp_path / "checkpoint-backfill-invalid.sqlite"
    plan, initial = _branch(path)
    checkpoint = _admitted(initial)
    proposal, decision = _adjudication(plan, checkpoint)
    historical = audit_current_action(
        checkpoint,
        trial_plan=plan,
        proposal=proposal,
        decision=decision,
    )
    tampered = dict(historical)
    tampered["current_action_audit_ref"] = "adjudication:other"
    tampered = seal_checkpoint(without_checkpoint_hash(tampered))
    with connect_sqlite(path) as conn:
        with pytest.raises(ValueError, match="audit_ref"):
            backfill_action_adjudication_receipt(
                conn,
                instance_id="instance-1",
                branch_id="branch-historical",
                trial_plan=plan,
                checkpoint=tampered,
                proposal=proposal,
                decision=decision,
            )


def test_missing_receipt_table_is_a_legacy_unavailable_read(tmp_path) -> None:
    path = tmp_path / "checkpoint-no-receipt-table.sqlite"
    with connect_sqlite(path) as conn:
        assert load_action_adjudication_receipt(
            conn, "instance-1", "branch-1", "a" * 64, "action:ic",
        ) is None
