from __future__ import annotations

from copy import deepcopy

import orjson
import pytest
from flask import Flask

import settings as Settings
from server.modules.single_factor_test import sft_bp
from server.services.research_run_schema import ensure_schema as ensure_run_schema
from server.services.research_graph.trial_plan import (
    initial_execution_checkpoint,
    trial_plan_hash,
)
from server.services.research_graph.trial_plan.execution_checkpoint_contract import (
    seal_checkpoint,
)
from server.services.research_graph.trial_plan.revision import (
    revise_current_trial_plan,
)
from server.services.research_graph.research_cycle.replay import (
    validate_research_cycle_checkpoint,
)
from server.services.research_graph.work_packages import insert_active
from tests.server.test_trial_plan_contract_v5 import trial_plan_v5
from tests.server.trial_plan_fixtures import initialize_branch
from tools.data.sqlite.db import connect_sqlite


def _seed(path) -> tuple[dict, dict]:
    original = trial_plan_v5()
    original_hash = trial_plan_hash(original)
    checkpoint = initial_execution_checkpoint(
        trial_plan=original,
        expected_trial_plan_hash=original_hash,
        execution_node="trial_execution",
    )
    initialize_branch(path, original_hash)
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
                "trial_plan": original,
                "trial_plan_hash": original_hash,
            }).decode(),),
        )
    revised = deepcopy(original)
    revised["version"] = 2
    revised["parent_trial_plan_hash"] = original_hash
    revised["samples"][0]["run_spec_hashes"] = ["c" * 64]
    revised["comparisons"][0]["members"][0]["run_spec_hash"] = "c" * 64
    revised["evidence_actions"][0]["run_spec_hashes"] = ["c" * 64]
    revised["evidence_actions"][0]["input_hash"] = "7" * 64
    return checkpoint, revised


def test_running_action_without_results_can_supersede_plan(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "trial-plan-revision.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    checkpoint, revised = _seed(path)
    from server.services.research_graph.trial_plan.execution_checkpoint_api import (
        operate_execution_checkpoint,
    )

    released = operate_execution_checkpoint(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        expected_latest_trace_id="trace-plan",
        expected_checkpoint_hash=checkpoint["projection_hash"],
        operation="release",
    )["checkpoint"]
    running = operate_execution_checkpoint(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        expected_latest_trace_id="trace-plan",
        expected_checkpoint_hash=released["projection_hash"],
        operation="mark_running",
    )["checkpoint"]

    result = revise_current_trial_plan(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        expected_latest_trace_id="trace-plan",
        expected_checkpoint_hash=running["projection_hash"],
        expected_trial_plan_hash=trial_plan_hash(trial_plan_v5()),
        trial_plan=revised,
    )

    assert result["previous_trial_plan_hash"] == trial_plan_hash(
        trial_plan_v5()
    )
    assert result["trial_plan_hash"] == trial_plan_hash(revised)
    assert result["checkpoint"]["current_action_status"] == "unreleased"
    assert result["checkpoint"]["current_action_input_hash"] == "7" * 64
    with connect_sqlite(path) as conn:
        branch = conn.execute(
            """
            SELECT current_trial_plan_hash, latest_trace_id
            FROM research_graph_branches WHERE branch_id='branch-1'
            """
        ).fetchone()
        instance = conn.execute(
            "SELECT workspace_id FROM research_graph_instances "
            "WHERE instance_id='instance-1'"
        ).fetchone()
        trace = conn.execute(
            "SELECT evidence_json FROM research_graph_trace "
            "WHERE trace_id=?",
            (branch["latest_trace_id"],),
        ).fetchone()
    evidence = orjson.loads(trace["evidence_json"])
    assert branch["current_trial_plan_hash"] == trial_plan_hash(revised)
    assert instance["workspace_id"] == "workspace-1"
    assert evidence["trial_plan_hash"] == trial_plan_hash(revised)
    assert evidence["trial_plan"]["parent_trial_plan_hash"] == (
        trial_plan_hash(trial_plan_v5())
    )


def test_blocked_action_without_results_resets_to_unreleased(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "trial-plan-revision-blocked.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    checkpoint, revised = _seed(path)
    blocked = deepcopy(checkpoint)
    blocked["current_action_status"] = "blocked"
    blocked.pop("projection_hash")
    blocked = seal_checkpoint(blocked)
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            UPDATE research_graph_branches
            SET trial_stage_projection_json=?
            WHERE instance_id='instance-1' AND branch_id='branch-1'
            """,
            (orjson.dumps(blocked).decode(),),
        )

    result = revise_current_trial_plan(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        expected_latest_trace_id="trace-plan",
        expected_checkpoint_hash=blocked["projection_hash"],
        expected_trial_plan_hash=trial_plan_hash(trial_plan_v5()),
        trial_plan=revised,
    )

    assert result["checkpoint"]["current_action_status"] == "unreleased"
    assert result["checkpoint"]["current_action_output_evidence_refs"] == []


def test_trial_plan_revision_rejects_any_bound_run(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "trial-plan-revision-run.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    checkpoint, revised = _seed(path)
    current_hash = trial_plan_hash(trial_plan_v5())
    with connect_sqlite(path) as conn:
        ensure_run_schema(conn)
        conn.execute(
            """
            INSERT INTO research_runs (
                run_id, owner, workspace_id, configuration_id,
                configuration_revision, kind, run_spec_version,
                run_spec_hash, run_spec_json, trial_plan_hash,
                graph_instance_id, graph_branch_id, evidence_action_id,
                created_at
            ) VALUES (
                'run-1', 'alice', 'workspace-1', 'config-1', 1, 'ic', 2,
                ?, '{}', ?, 'instance-1', 'branch-1', 'action:ic', 2
            )
            """,
            ("c" * 64, current_hash),
        )

    with pytest.raises(ValueError, match="existing Run or Job"):
        revise_current_trial_plan(
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            expected_latest_trace_id="trace-plan",
            expected_checkpoint_hash=checkpoint["projection_hash"],
            expected_trial_plan_hash=current_hash,
            trial_plan=revised,
        )


def test_trial_plan_revision_rejects_action_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "trial-plan-revision-evidence.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    checkpoint, revised = _seed(path)
    from server.services.research_graph.trial_plan.execution_checkpoint_api import (
        operate_execution_checkpoint,
    )

    released = operate_execution_checkpoint(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        expected_latest_trace_id="trace-plan",
        expected_checkpoint_hash=checkpoint["projection_hash"],
        operation="release",
    )["checkpoint"]
    ready = operate_execution_checkpoint(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        expected_latest_trace_id="trace-plan",
        expected_checkpoint_hash=released["projection_hash"],
        operation="mark_evidence_ready",
        payload={"evidence_refs": ["evidence:ic-result"]},
    )["checkpoint"]

    with pytest.raises(ValueError, match="unused current Action"):
        revise_current_trial_plan(
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            expected_latest_trace_id="trace-plan",
            expected_checkpoint_hash=ready["projection_hash"],
            expected_trial_plan_hash=trial_plan_hash(trial_plan_v5()),
            trial_plan=revised,
        )


def test_trial_plan_revision_route_uses_exact_current_identity(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "trial-plan-revision-route.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    checkpoint, revised = _seed(path)
    app = Flask(__name__)
    app.secret_key = "trial-plan-revision"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"
    response = client.post(
        "/api/research-graph-instances/instance-1/branches/branch-1/"
        "trial-plan/revisions",
        json={
            "expected_latest_trace_id": "trace-plan",
            "expected_checkpoint_hash": checkpoint["projection_hash"],
            "expected_trial_plan_hash": trial_plan_hash(trial_plan_v5()),
            "trial_plan": revised,
        },
    )

    assert response.status_code == 201, response.get_data(as_text=True)
    value = response.get_json()["revision"]
    assert value["trial_plan_hash"] == trial_plan_hash(revised)
    stale = client.post(
        "/api/research-graph-instances/instance-1/branches/branch-1/"
        "trial-plan/revisions",
        json={
            "expected_latest_trace_id": "trace-plan",
            "expected_checkpoint_hash": checkpoint["projection_hash"],
            "expected_trial_plan_hash": trial_plan_hash(trial_plan_v5()),
            "trial_plan": revised,
        },
    )
    assert stale.status_code == 409


def test_trial_plan_revision_rebinds_research_cycle_checkpoint(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "trial-plan-revision-cycle.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    checkpoint, revised = _seed(path)
    current_hash = trial_plan_hash(trial_plan_v5())
    cycle = validate_research_cycle_checkpoint({
        "schema_version": 1,
        "contract_hash": "3" * 64,
        "trial_plan_hash": current_hash,
        "methodology_hash": "4" * 64,
        "claims": [],
        "obligations": [],
        "pending_adjudications": [],
        "pending_closure": None,
    })
    with connect_sqlite(path) as conn:
        evidence = {
            "trial_plan": trial_plan_v5(),
            "trial_plan_hash": current_hash,
            "research_cycle_checkpoint": cycle,
        }
        conn.execute(
            "UPDATE research_graph_trace SET evidence_json=? "
            "WHERE trace_id='trace-plan'",
            (orjson.dumps(evidence).decode(),),
        )

    result = revise_current_trial_plan(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        expected_latest_trace_id="trace-plan",
        expected_checkpoint_hash=checkpoint["projection_hash"],
        expected_trial_plan_hash=current_hash,
        trial_plan=revised,
    )
    with connect_sqlite(path) as conn:
        row = conn.execute(
            "SELECT evidence_json FROM research_graph_trace WHERE trace_id=?",
            (result["latest_trace_id"],),
        ).fetchone()
    evidence = orjson.loads(row["evidence_json"])
    assert evidence["research_cycle_checkpoint"]["trial_plan_hash"] == (
        trial_plan_hash(revised)
    )
    assert evidence["research_cycle"]["events"] == [{
        "event_type": "trial_plan_bound",
        "from_hash": current_hash,
        "to_hash": trial_plan_hash(revised),
    }]
