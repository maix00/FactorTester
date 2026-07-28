"""Focused fixtures for request-bound data-contract transition tests."""

from __future__ import annotations

from datetime import datetime, timezone

import orjson

from server.services.research_graph.branch.schema import (
    create_instance_branch_schema,
)
from server.services.research_graph.graph_objects import (
    create_graph_object_schema,
)
from server.services.research_graph.research_cycle.replay import (
    validate_research_cycle_checkpoint,
)
from tools.data.availability.model import profile_document
from tools.data.sqlite.db import connect_sqlite


def checkpoint(*, obligation_status: str = "bounded") -> dict:
    return validate_research_cycle_checkpoint({
        "schema_version": 1,
        "contract_hash": "1" * 64,
        "trial_plan_hash": "",
        "methodology_hash": "2" * 64,
        "claims": [{
            "schema_version": 1,
            "claim_id": "claim-data",
            "contract_hash": "1" * 64,
            "claim_ref": "factor-claim:data",
            "claim_type": "bounded_predictive_relationship",
            "scope": {"product_group": "CNFutures"},
            "evidence_state": "unknown",
            "evidence_refs": [],
        }],
        "obligations": [{
            "schema_version": 1,
            "obligation_id": "obligation-data",
            "contract_hash": "1" * 64,
            "claim_ids": ["claim-data"],
            "obligation_kind": "data_feasibility",
            "requirement_refs": [
                "data-availability.scope",
            ],
            "epistemic_question": "Is required minute history available?",
            "scope": {"product": "A.DCE", "frequency": "MIN1"},
            "discharge_criterion": {
                "method_ref": "availability-and-pit-review@1",
            },
            "status": obligation_status,
            "materiality": "decision_blocking",
            "methodology_hash": "2" * 64,
            "created_event_ref": "trace:data-contract-bootstrap",
        }],
        "pending_adjudications": [],
        "pending_closure": None,
    })


def graph() -> dict:
    return {
        "graph_id": "factor-research",
        "version": 1,
        "lifecycle": "active",
        "content_hash": "c" * 64,
        "entry_node": "data_contract",
        "nodes": [
            {
                "node_id": "data_contract",
                "kind": "research",
                "required_capabilities": [],
            },
            {
                "node_id": "factor_semantics",
                "kind": "research",
                "required_capabilities": [],
            },
            {
                "node_id": "capability_gap",
                "kind": "capability_gap",
                "required_capabilities": [],
            },
        ],
        "edges": [
            {
                "edge_id": "data_contract__factor_semantics",
                "from_node": "data_contract",
                "to_node": "factor_semantics",
                "guard": {
                    "data_availability_profile_bound": True,
                    "requested_product_availability_present": True,
                    "material_data_obligations_adjudicated_or_not_triggered": True,
                },
                "required_evidence": [],
                "server_action": "bind_data_availability",
            },
            {
                "edge_id": "data_contract__capability_gap",
                "from_node": "data_contract",
                "to_node": "capability_gap",
                "edge_type": "failure",
                "guard": {
                    "data_availability_profile_bound": True,
                    "requested_product_availability_present": False,
                },
                "required_evidence": [],
                "server_action": "bind_data_availability",
            },
            {
                "edge_id": "capability_gap__data_contract",
                "from_node": "capability_gap",
                "to_node": "data_contract",
                "edge_type": "recovery",
                "guard": {
                    "data_availability_profile_bound": True,
                    "requested_product_availability_present": True,
                },
                "required_evidence": [],
                "server_action": "bind_data_availability",
            },
        ],
    }


def initialize(path, *, obligation_status: str = "bounded") -> None:
    evidence = {
        "research_cycle_checkpoint": checkpoint(
            obligation_status=obligation_status,
        ),
        "evidence_refs": [],
    }
    with connect_sqlite(path) as conn:
        create_instance_branch_schema(conn)
        create_graph_object_schema(conn)
        conn.execute(
            """
            CREATE TABLE research_graph_versions (
                graph_id TEXT NOT NULL, version INTEGER NOT NULL,
                lifecycle TEXT NOT NULL, parent_version INTEGER NOT NULL,
                content_hash TEXT NOT NULL, graph_json TEXT NOT NULL,
                created_by TEXT NOT NULL, created_at REAL NOT NULL,
                PRIMARY KEY (graph_id, version)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO research_graph_versions VALUES (
                'factor-research', 1, 'active', 0, 'cccc',
                ?, 'curator', 1
            )
            """,
            (orjson.dumps(graph()).decode(),),
        )
        conn.execute(
            """
            INSERT INTO research_graph_instances (
                instance_id, owner, graph_id, graph_version, product_group,
                workspace_id, mode, shadow_run_id, created_at
            ) VALUES (
                'instance-1', 'alice', 'factor-research', 1, 'CNFutures',
                'workspace-1', 'live', '', 1
            )
            """
        )
        conn.execute(
            """
            INSERT INTO research_graph_branches (
                branch_id, instance_id, label, current_node, status,
                current_capability_resolution_json,
                current_capability_resolution_hash,
                current_trial_plan_hash, evidence_refs_json,
                latest_trace_id, created_at, updated_at
            ) VALUES (
                'branch-1', 'instance-1', 'primary', 'data_contract',
                'running', '{}', '', '', '[]',
                'trace-bootstrap', 1, 1
            )
            """
        )
        conn.execute(
            """
            INSERT INTO research_graph_trace (
                trace_id, instance_id, branch_id, edge_id, from_node, to_node,
                evidence_json, telemetry_json, actor, created_at
            ) VALUES (
                'trace-bootstrap', 'instance-1', 'branch-1', 'bootstrap',
                'data_contract', 'data_contract', ?, '{}', 'alice', 1
            )
            """,
            (orjson.dumps(evidence).decode(),),
        )


def profile(*, status: str = "available") -> dict:
    return profile_document(
        product_scope=["A.DCE"],
        source_scope=["Local"],
        frequency_scope=["MIN1"],
        probe=False,
        expanded=False,
        entries=[{
            "product": "A.DCE",
            "source": "LocalCNFuturesMIN1",
            "mode": "historical_snapshot",
            "status": status,
            "frequency": "MIN1",
            "replayable": status == "available",
        }],
        as_of=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )


def transition_evidence() -> dict:
    return {
        "data_availability_request": {
            "products": ["A.DCE"],
            "sources": ["Local"],
            "frequencies": ["MIN1"],
            "probe": False,
            "expanded": False,
        },
        "data_availability_profile_bound": False,
        "requested_product_availability_present": False,
        "material_data_obligations_adjudicated_or_not_triggered": True,
    }
