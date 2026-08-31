"""Current Research Cycle bodies are loaded explicitly by compact ID."""

from __future__ import annotations

import orjson
import pytest
from flask import Flask

import settings as Settings
from server.modules.single_factor_test import sft_bp
from server.services.research_graph.branch import cycle_objects
from server.services.research_graph.research_cycle.replay import (
    validate_research_cycle_checkpoint,
)
from server.services.research_graph.research_cycle.evidence import (
    validate_agent_evidence_envelope,
)
from server.services.research_graph.trial_plan import trial_plan_hash
from server.services import research_runs
from tests.server.trial_plan_fixtures import initialize_branch, trial_plan
from tools.data.sqlite.db import connect_sqlite


def _checkpoint() -> dict:
    return validate_research_cycle_checkpoint({
        "schema_version": 1,
        "contract_hash": "1" * 64,
        "trial_plan_hash": "2" * 64,
        "methodology_hash": "3" * 64,
        "claims": [{
            "schema_version": 1,
            "claim_id": "claim-read",
            "contract_hash": "1" * 64,
            "claim_ref": "factor-claim:read",
            "claim_type": "bounded_predictive_relationship",
            "scope": {"product_group": "CNFutures"},
            "evidence_state": "unknown",
            "evidence_refs": [],
        }],
        "obligations": [{
            "schema_version": 1,
            "obligation_id": "obligation-read",
            "title_zh": "机制存续性",
            "contract_hash": "1" * 64,
            "claim_ids": ["claim-read"],
            "obligation_kind": "semantic_test",
            "epistemic_question": "Does the stated mechanism survive?",
            "scope": {"product_group": "CNFutures"},
            "discharge_criterion": {"rule_ref": "semantic:survival"},
            "status": "open",
            "materiality": "decision_blocking",
            "methodology_hash": "3" * 64,
            "created_event_ref": "trace:init",
        }],
        "pending_adjudications": [],
        "pending_closure": None,
    })


def _seed(path) -> None:
    initialize_branch(path, "2" * 64)
    plan = trial_plan("4" * 64)
    envelope = validate_agent_evidence_envelope({
        "schema_version": 2,
        "envelope_id": "factor-semantics:read",
        "evidence_kind": "factor_semantics",
        "source_refs": ["factor-revision:read"],
        "identity_refs": {
            "contract_hash": "1" * 64,
            "methodology_hash": "3" * 64,
        },
        "facts": {"selected_factor_semantics_resolved": True},
        "metric_refs": [],
        "artifact_refs": [],
        "hypotheses_tested": 0,
        "stop_condition": None,
        "limitations": ["Timing remains a separate obligation."],
        "conflicts": [],
    })
    evidence = {
        "research_cycle_checkpoint": _checkpoint(),
        "trial_plan": plan,
        "trial_plan_hash": trial_plan_hash(plan),
        "server_evidence": {"factor_semantics": envelope},
        "evidence_refs": ["evidence:" + envelope["envelope_hash"]],
    }
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id,
                from_node, to_node, evidence_json, telemetry_json,
                actor, created_at
            ) VALUES (
                'trace-current', 'instance-1', 'branch-1', 'cycle-event',
                'research_decision', 'research_decision', ?, '{}', 'alice', 1
            )
            """,
            (orjson.dumps(evidence).decode(),),
        )
        conn.execute(
            """
            UPDATE research_graph_branches
            SET latest_trace_id='trace-current'
            WHERE branch_id='branch-1'
            """
        )


def test_cycle_object_read_returns_one_body_with_one_database_read(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "cycle-object.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _seed(path)
    statements: list[str] = []

    def traced_connect(*args, **kwargs):
        conn = connect_sqlite(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(cycle_objects, "connect_sqlite", traced_connect)
    obligation = cycle_objects.load_research_cycle_object(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        object_type="obligation",
        object_id="obligation-read",
    )

    assert obligation["epistemic_question"] == (
        "Does the stated mechanism survive?"
    )
    assert obligation["discharge_criterion"] == {
        "rule_ref": "semantic:survival"
    }
    normalized = [" ".join(item.upper().split()) for item in statements]
    assert sum(item.startswith("SELECT") for item in normalized) == 1
    assert all("ORDER BY" not in item for item in normalized)


def test_cycle_object_read_supports_claim_and_rejects_unknown_id(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "cycle-claim.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _seed(path)

    claim = cycle_objects.load_research_cycle_object(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        object_type="claim",
        object_id="claim-read",
    )
    assert claim["claim_ref"] == "factor-claim:read"

    with pytest.raises(KeyError, match="not found"):
        cycle_objects.load_research_cycle_object(
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            object_type="obligation",
            object_id="missing",
        )


def test_cycle_object_read_supports_typed_trial_plan_and_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "cycle-typed.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _seed(path)
    with connect_sqlite(path) as conn:
        persisted = orjson.loads(conn.execute(
            "SELECT evidence_json FROM research_graph_trace "
            "WHERE trace_id='trace-current'"
        ).fetchone()["evidence_json"])
    evidence_hash = persisted["server_evidence"]["factor_semantics"][
        "envelope_hash"
    ]
    statements: list[str] = []

    def traced_connect(*args, **kwargs):
        conn = connect_sqlite(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(cycle_objects, "connect_sqlite", traced_connect)

    plan = cycle_objects.load_research_cycle_object(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        object_type="trial_plan",
        object_id="plan-1",
        trace_id="trace-current",
    )
    envelope = cycle_objects.load_research_cycle_object(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        object_type="evidence",
        object_id=evidence_hash,
        trace_id="trace-current",
    )

    assert plan["protocol_ref"] == "cross-sectional-ic@1"
    assert envelope["evidence_kind"] == "factor_semantics"
    assert envelope["facts"] == {
        "selected_factor_semantics_resolved": True,
    }
    normalized = [" ".join(item.upper().split()) for item in statements]
    assert sum(item.startswith("SELECT") for item in normalized) == 2
    assert all("ORDER BY" not in item for item in normalized)


def test_cycle_object_read_validates_exact_task_reference(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "cycle-task.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _seed(path)
    with connect_sqlite(path) as conn:
        evidence = orjson.loads(conn.execute(
            "SELECT evidence_json FROM research_graph_trace "
            "WHERE trace_id='trace-current'"
        ).fetchone()["evidence_json"])
        evidence["review"] = {"task_ref": "research-cycle-review:abc"}
        conn.execute(
            "UPDATE research_graph_trace SET evidence_json=? "
            "WHERE trace_id='trace-current'",
            (orjson.dumps(evidence).decode(),),
        )

    task = cycle_objects.load_research_cycle_object(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        object_type="task",
        object_id="research-cycle-review:abc",
    )

    assert task == {
        "schema_version": 1,
        "object_kind": "task",
        "task_ref": "research-cycle-review:abc",
    }
    with pytest.raises(KeyError, match="not found"):
        cycle_objects.load_research_cycle_object(
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            object_type="task",
            object_id="research-cycle-review:missing",
        )


def test_cycle_object_read_derives_delta_from_requested_trace(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "cycle-delta.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _seed(path)
    with connect_sqlite(path) as conn:
        persisted = orjson.loads(conn.execute(
            "SELECT evidence_json FROM research_graph_trace "
            "WHERE trace_id='trace-current'"
        ).fetchone()["evidence_json"])
        persisted["research_cycle"] = {
            "accepted_deltas": {
                "obligation_deltas": [{
                    "obligation_id": "obligation-read",
                    "from_state": "open",
                    "to_state": "serviced",
                }],
                "claim_deltas": [{
                    "claim_id": "claim-read",
                    "from_state": "unknown",
                    "to_state": "inconclusive",
                }],
            },
        }
        conn.execute(
            "UPDATE research_graph_trace SET evidence_json=? "
            "WHERE trace_id='trace-current'",
            (orjson.dumps(persisted).decode(),),
        )

    delta = cycle_objects.load_research_cycle_object(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        object_type="delta",
        object_id="trace-current:obligation:obligation-read",
        trace_id="trace-current",
    )
    assert delta == {
        "schema_version": 1,
        "delta_ref": "delta:trace-current:obligation:obligation-read",
        "trace_ref": "trace:trace-current",
        "object_kind": "obligation",
        "object_id": "obligation-read",
        "from_state": "open",
        "to_state": "serviced",
    }
    with pytest.raises(KeyError, match="not found"):
        cycle_objects.load_research_cycle_object(
            instance_id="instance-1",
            branch_id="branch-1",
            owner="alice",
            object_type="delta",
            object_id="trace-current:obligation:missing",
            trace_id="trace-current",
        )


def test_cycle_object_read_lazy_loads_exact_immutable_run_configuration(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "cycle-run.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _seed(path)
    run = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-1",
        configuration_revision=7,
        run_spec={
            "run_spec_version": 4,
            "products": ["RB.SHF"],
            "start_date": "2024-01-01",
            "end_date": "2025-12-31",
            "end_session_skip": False,
        },
    )
    with connect_sqlite(path) as conn:
        evidence = orjson.loads(conn.execute(
            "SELECT evidence_json FROM research_graph_trace "
            "WHERE trace_id='trace-current'"
        ).fetchone()["evidence_json"])
        evidence["run_id"] = run["run_id"]
        evidence["run_spec_hash"] = run["run_spec_hash"]
        conn.execute(
            "UPDATE research_graph_trace SET evidence_json=? "
            "WHERE trace_id='trace-current'",
            (orjson.dumps(evidence).decode(),),
        )

    value = cycle_objects.load_research_cycle_object(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        object_type="run",
        object_id=run["run_id"],
        trace_id="trace-current",
    )
    run_spec = cycle_objects.load_research_cycle_object(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        object_type="run_spec",
        object_id="sha256:" + run["run_spec_hash"],
        trace_id="trace-current",
    )

    assert value["object_kind"] == "run"
    assert value["configuration_revision"] == 7
    assert value["run_spec_hash"] == run["run_spec_hash"]
    assert value["run_spec"]["end_session_skip"] is False
    assert '"products": [\n    "RB.SHF"\n  ]' in value["run_spec_json"]
    assert run_spec["object_kind"] == "run_spec"
    assert run_spec["run_spec_hash"] == run["run_spec_hash"]
    assert run_spec["configuration_revision"] == 7
    assert '"products": [\n    "RB.SHF"\n  ]' in (
        run_spec["complete_parameters_json"]
    )
    with pytest.raises(KeyError, match="not found"):
        cycle_objects.load_research_cycle_object(
            instance_id="instance-1",
            branch_id="branch-1",
            owner="bob",
            object_type="run",
            object_id=run["run_id"],
            trace_id="trace-current",
        )

def test_cycle_object_read_is_bound_to_requested_historical_trace(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "cycle-history.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _seed(path)
    historical = _checkpoint()
    historical.pop("projection_hash")
    historical["obligations"][0]["status"] = "open"
    historical["obligations"][0]["epistemic_question"] = (
        "What was still unknown at preregistration?"
    )
    historical = validate_research_cycle_checkpoint(historical)
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id,
                from_node, to_node, evidence_json, telemetry_json,
                actor, created_at
            ) VALUES (
                'trace-history', 'instance-1', 'branch-1', 'older-event',
                'preregistration', 'factor_semantics', ?, '{}', 'alice', 0
            )
            """,
            (orjson.dumps({
                "research_cycle_checkpoint": historical,
            }).decode(),),
        )

    obligation = cycle_objects.load_research_cycle_object(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        object_type="obligation",
        object_id="obligation-read",
        trace_id="trace-history",
    )

    assert obligation["epistemic_question"] == (
        "What was still unknown at preregistration?"
    )


def test_cycle_object_route_preserves_checkpoint_and_owner_scope(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "cycle-route.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    _seed(path)
    historical = _checkpoint()
    historical.pop("projection_hash")
    historical["obligations"][0]["epistemic_question"] = (
        "What did Alice know at this checkpoint?"
    )
    historical = validate_research_cycle_checkpoint(historical)
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id,
                from_node, to_node, evidence_json, telemetry_json,
                actor, created_at
            ) VALUES (
                'trace-route-history', 'instance-1', 'branch-1',
                'older-event', 'preregistration', 'factor_semantics',
                ?, '{}', 'alice', 0
            )
            """,
            (orjson.dumps({
                "research_cycle_checkpoint": historical,
            }).decode(),),
        )
    app = Flask(__name__)
    app.secret_key = "cycle-route-test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    href = (
        "/api/research-graph-instances/instance-1/branches/branch-1/"
        "cycle-objects/obligation/obligation-read"
    )
    with client.session_transaction() as session:
        session["username"] = "alice"
    response = client.get(
        href,
        query_string={"trace_id": "trace-route-history"},
    )
    assert response.status_code == 200
    assert response.get_json()["object"]["epistemic_question"] == (
        "What did Alice know at this checkpoint?"
    )

    with client.session_transaction() as session:
        session["username"] = "bob"
    assert client.get(
        href,
        query_string={"trace_id": "trace-route-history"},
    ).status_code == 404
