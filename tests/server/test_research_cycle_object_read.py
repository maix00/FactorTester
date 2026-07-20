"""Current Research Cycle bodies are loaded explicitly by compact ID."""

from __future__ import annotations

import orjson
import pytest

import settings as Settings
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
