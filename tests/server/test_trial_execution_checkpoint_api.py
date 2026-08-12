"""Public server contract for TrialPlan v5 Evidence Action execution."""

from __future__ import annotations

from copy import deepcopy

import orjson
import pytest
from flask import Flask

import settings as Settings
from server.modules.single_factor_test import sft_bp
from server.services.research_graph.trial_plan import (
    ExecutionCheckpointConflictError,
    initial_execution_checkpoint,
    trial_plan_hash,
)
from server.services.research_graph.trial_plan.execution_checkpoint_api import (
    current_action_trial_binding,
    load_execution_checkpoint_contract,
    operate_execution_checkpoint,
    recover_missing_execution_checkpoint,
)
from server.services.research_graph.work_packages import insert_active
from tests.server.test_trial_plan_contract_v5 import trial_plan_v5
from tests.server.trial_plan_fixtures import initialize_branch
from tools.data.sqlite.db import connect_sqlite


def _stored_current_plan(path, *, plan: dict | None = None) -> dict:
    value = plan or trial_plan_v5()
    plan_hash = trial_plan_hash(value)
    checkpoint = initial_execution_checkpoint(
        trial_plan=value,
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
            SET current_node='trial_execution', latest_trace_id='trace-plan',
                trial_stage_projection_json=?
            WHERE branch_id='branch-1'
            """,
            (orjson.dumps(checkpoint).decode(),),
        )
        conn.execute(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id, from_node, to_node,
                evidence_json, telemetry_json, actor, acting_profile_ref,
                created_at
            ) VALUES (
                'trace-plan', 'instance-1', 'branch-1', 'freeze-plan',
                'validation_design', 'trial_execution', ?, '{}',
                'alice', '', 1
            )
            """,
            (orjson.dumps({
                "trial_plan": value,
                "trial_plan_hash": plan_hash,
            }).decode(),),
        )
    return checkpoint


def _empty_current_plan(path) -> None:
    _stored_current_plan(path)
    with connect_sqlite(path) as conn:
        conn.execute(
            "UPDATE research_graph_branches "
            "SET trial_stage_projection_json='{}' "
            "WHERE branch_id='branch-1'"
        )


def test_read_release_and_generate_current_action_binding(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "execution-api.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    initial = _stored_current_plan(path)

    contract = load_execution_checkpoint_contract(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
    )
    assert contract["checkpoint"] == initial
    assert contract["allowed_operations"] == ["release"]
    released = operate_execution_checkpoint(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        expected_latest_trace_id="trace-plan",
        expected_checkpoint_hash=initial["projection_hash"],
        operation="release",
    )["checkpoint"]
    binding = current_action_trial_binding(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        run_spec_hash="a" * 64,
        trial_role="baseline",
        comparison_id="comparison:parent-child",
    )
    assert released["current_action_status"] == "released"
    assert binding["trial_plan_hash"] == trial_plan_hash(trial_plan_v5())
    assert binding["evidence_action_id"] == "action:ic"
    assert binding["expected_checkpoint_hash"] == released["projection_hash"]
    assert binding["expected_latest_trace_id"] == "trace-plan"


def test_public_operation_rejects_stale_cas_and_wrong_current_plan(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "execution-api-conflict.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    initial = _stored_current_plan(path)
    with pytest.raises(ExecutionCheckpointConflictError, match="trace"):
        operate_execution_checkpoint(
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            expected_latest_trace_id="trace-stale",
            expected_checkpoint_hash=initial["projection_hash"],
            operation="release",
        )

    wrong = deepcopy(trial_plan_v5())
    wrong["trial_plan_id"] = "wrong-plan"
    with connect_sqlite(path) as conn:
        conn.execute(
            "UPDATE research_graph_trace SET evidence_json=? "
            "WHERE trace_id='trace-plan'",
            (orjson.dumps({
                "trial_plan": wrong,
                "trial_plan_hash": trial_plan_hash(trial_plan_v5()),
            }).decode(),),
        )
    with pytest.raises(ValueError, match="does not match branch"):
        load_execution_checkpoint_contract(
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
        )


def test_current_plan_lookup_never_reads_a_sibling_branch(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "execution-api-sibling.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    expected = _stored_current_plan(path)
    wrong = deepcopy(trial_plan_v5())
    wrong["trial_plan_id"] = "sibling-plan"
    plan_hash = trial_plan_hash(trial_plan_v5())
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            INSERT INTO research_graph_branches (
                branch_id, instance_id, label, current_node, status,
                current_capability_resolution_json,
                current_capability_resolution_hash,
                current_trial_plan_hash, latest_trace_id,
                trial_stage_projection_json, created_at, updated_at
            ) VALUES (
                'branch-sibling', 'instance-1', 'sibling', 'trial_execution',
                'running', '{}', '', ?, 'trace-sibling', ?, 2, 2
            )
            """,
            (plan_hash, orjson.dumps(expected).decode()),
        )
        conn.execute(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id, from_node, to_node,
                evidence_json, telemetry_json, actor, acting_profile_ref,
                created_at
            ) VALUES (
                'trace-sibling', 'instance-1', 'branch-sibling', 'freeze-plan',
                'validation_design', 'trial_execution', ?, '{}',
                'alice', '', 2
            )
            """,
            (orjson.dumps({
                "trial_plan": wrong,
                "trial_plan_hash": plan_hash,
            }).decode(),),
        )

    contract = load_execution_checkpoint_contract(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
    )
    assert contract["trial_plan"]["trial_plan_id"] == "plan-v5"
    assert contract["checkpoint"] == expected


def test_flask_routes_enforce_owner_and_expose_checkpoint_release_binding(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "execution-api-routes.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    initial = _stored_current_plan(path)
    app = Flask(__name__)
    app.secret_key = "trial-execution-route-test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    checkpoint_url = (
        "/api/research-graph-instances/instance-1/branches/branch-1/"
        "trial-execution-checkpoint"
    )

    with client.session_transaction() as session:
        session["username"] = "bob"
    assert client.get(checkpoint_url).status_code == 404

    with client.session_transaction() as session:
        session["username"] = "alice"
    read = client.get(checkpoint_url)
    assert read.status_code == 200
    execution = read.get_json()["execution"]
    assert execution["trial_plan_hash"] == trial_plan_hash(trial_plan_v5())
    assert execution["latest_trace_id"] == "trace-plan"
    assert execution["checkpoint"]["projection_hash"] == (
        initial["projection_hash"]
    )
    assert execution["allowed_operations"] == ["release"]

    release = client.post(
        checkpoint_url + "/operations",
        json={
            "expected_latest_trace_id": execution["latest_trace_id"],
            "expected_checkpoint_hash": initial["projection_hash"],
            "operation": "release",
            "payload": {},
        },
    )
    assert release.status_code == 200
    released = release.get_json()["result"]["checkpoint"]
    assert released["current_action_status"] == "released"

    stale = client.post(
        checkpoint_url + "/operations",
        json={
            "expected_latest_trace_id": execution["latest_trace_id"],
            "expected_checkpoint_hash": initial["projection_hash"],
            "operation": "mark_running",
            "payload": {},
        },
    )
    assert stale.status_code == 409
    assert "checkpoint changed" in stale.get_json()["error"]

    binding = client.get(
        checkpoint_url.removesuffix("trial-execution-checkpoint")
        + "trial-execution-binding",
        query_string={
            "run_spec_hash": "a" * 64,
            "trial_role": "baseline",
            "comparison_id": "comparison:parent-child",
        },
    )
    assert binding.status_code == 200
    value = binding.get_json()["trial_binding"]
    assert value["trial_plan_hash"] == execution["trial_plan_hash"]
    assert value["evidence_action_id"] == "action:ic"
    assert value["expected_checkpoint_hash"] == released["projection_hash"]
    assert value["expected_latest_trace_id"] == "trace-plan"


def test_recovery_initializes_only_exact_empty_v5_checkpoint_with_cas(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "execution-api-recovery.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _empty_current_plan(path)
    recovered = recover_missing_execution_checkpoint(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        expected_latest_trace_id="trace-plan",
        expected_execution_node="trial_execution",
    )
    assert recovered["operation"] == "initialize_missing"
    assert recovered["previous_checkpoint"] == {}
    assert recovered["checkpoint"]["current_action_id"] == "action:ic"
    assert recovered["checkpoint"]["current_action_status"] == "unreleased"
    with connect_sqlite(path) as conn:
        row = conn.execute(
            "SELECT current_node, latest_trace_id, "
            "trial_stage_projection_json FROM research_graph_branches "
            "WHERE branch_id='branch-1'"
        ).fetchone()
        trace_count = conn.execute(
            "SELECT COUNT(*) AS count FROM research_graph_trace"
        ).fetchone()["count"]
    assert row["current_node"] == "trial_execution"
    assert row["latest_trace_id"] == "trace-plan"
    assert orjson.loads(row["trial_stage_projection_json"]) == (
        recovered["checkpoint"]
    )
    assert trace_count == 1

    with pytest.raises(ValueError, match="requires exact"):
        recover_missing_execution_checkpoint(
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            expected_latest_trace_id="trace-plan",
            expected_execution_node="trial_execution",
        )


@pytest.mark.parametrize(
    ("expected_trace", "expected_node", "message"),
    [
        ("trace-stale", "trial_execution", "trace changed"),
        ("trace-plan", "wrong_node", "expected execution node"),
    ],
)
def test_recovery_rejects_stale_trace_or_wrong_node(
    tmp_path,
    monkeypatch,
    expected_trace,
    expected_node,
    message,
) -> None:
    path = tmp_path / f"execution-api-recovery-{expected_node}.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _empty_current_plan(path)
    with pytest.raises(ValueError, match=message):
        recover_missing_execution_checkpoint(
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            expected_latest_trace_id=expected_trace,
            expected_execution_node=expected_node,
        )


def test_recovery_rejects_wrong_current_plan_body(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "execution-api-recovery-wrong-plan.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _empty_current_plan(path)
    wrong = deepcopy(trial_plan_v5())
    wrong["trial_plan_id"] = "wrong-plan"
    with connect_sqlite(path) as conn:
        conn.execute(
            "UPDATE research_graph_trace SET evidence_json=? "
            "WHERE trace_id='trace-plan'",
            (orjson.dumps({
                "trial_plan": wrong,
                "trial_plan_hash": trial_plan_hash(trial_plan_v5()),
            }).decode(),),
        )
    with pytest.raises(ValueError, match="does not match branch"):
        recover_missing_execution_checkpoint(
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            expected_latest_trace_id="trace-plan",
            expected_execution_node="trial_execution",
        )


def test_recovery_route_returns_receipt_and_conflict_status(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "execution-api-recovery-route.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _empty_current_plan(path)
    app = Flask(__name__)
    app.secret_key = "trial-recovery-route-test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"
    url = (
        "/api/research-graph-instances/instance-1/branches/branch-1/"
        "trial-execution-checkpoint/recover"
    )
    response = client.post(url, json={
        "expected_latest_trace_id": "trace-plan",
        "expected_execution_node": "trial_execution",
    })
    assert response.status_code == 200
    receipt = response.get_json()["recovery"]
    assert receipt["recovered"] is True
    assert receipt["latest_trace_id"] == "trace-plan"
    assert receipt["checkpoint"]["current_action_status"] == "unreleased"
    assert client.post(url, json={
        "expected_latest_trace_id": "trace-plan",
        "expected_execution_node": "trial_execution",
    }).status_code == 409
