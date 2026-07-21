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
from tests.server.trial_plan_fixtures import initialize_branch
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
    evidence = {"research_cycle_checkpoint": _checkpoint()}
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
