"""Shared deterministic fixtures for TrialPlan acceptance tests."""

from __future__ import annotations

import hashlib

import orjson

from server.jobs.models import JobRecord
from server.jobs.states import JobStatus
from server.services.research_graph.branch.schema import (
    create_instance_branch_schema,
)
from server.services.research_run_identity import RUN_SPEC_VERSION
from server.services.research_graph.trial_plan import trial_plan_hash
from tools.data.sqlite.db import connect_sqlite


def run_spec() -> dict:
    return {
        "run_spec_version": RUN_SPEC_VERSION,
        "workspace_id": "workspace-1",
        "analyses": ["ic"],
        "start_date": "2020-01-01",
        "end_date": "2023-12-31",
        "selected_paths": ["CNFutures/黑色"],
    }


def semantic_hash(value: dict) -> str:
    return hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


def trial_plan(run_spec_hash: str) -> dict:
    return {
        "schema_version": 1,
        "trial_plan_id": "plan-1",
        "version": 1,
        "hypothesis_ref": "hypothesis-1",
        "trial_family": "family-1",
        "protocol_ref": "cross-sectional-ic@1",
        "outcomes": {
            "primary": ["rank-ic"],
            "secondary": ["coverage"],
        },
        "sample_roles": [{
            "sample_ref": "selection-2020-2023",
            "sample_hash": "d" * 64,
            "role": "selection",
            "run_spec_hashes": [run_spec_hash],
        }],
        "comparisons": [{
            "comparison_id": "main-comparison",
            "members": [{
                "run_spec_hash": run_spec_hash,
                "trial_role": "selection",
            }],
        }],
        "stopping": {
            "rule_ref": "fixed-sample@1",
            "monitored_outcomes": ["rank-ic"],
            "parameters": {"minimum_observations": 250},
        },
        "multiplicity": {
            "method_ref": "none@1",
            "family_ref": "family-1",
            "dependence_assumptions": [],
        },
        "criteria": {
            "rejection_ref": "ic-reject@1",
            "revision_ref": "ic-revise@1",
            "continuation_ref": "ic-continue@1",
        },
    }


def trial_plan_v4() -> dict:
    value = trial_plan("a" * 64)
    value.update({
        "schema_version": 4,
        "decision_contract_hash": "1" * 64,
        "methodology_hash": "2" * 64,
        "obligation_refs": ["obligation-stage"],
        "parent_trial_plan_hash": None,
        "stage_policy": {
            "ordered_stages": [
                "selection",
                "validation",
                "confirmation",
            ],
            "entry_stage": "selection",
            "entry_basis_ref": "decision-contract:new-research",
        },
        "sample_roles": [
            {
                "sample_ref": "selection-2020-2022",
                "sample_hash": "d" * 64,
                "role": "selection",
                "run_spec_hashes": ["a" * 64],
            },
            {
                "sample_ref": "validation-2023",
                "sample_hash": "e" * 64,
                "role": "validation",
                "run_spec_hashes": ["b" * 64],
            },
            {
                "sample_ref": "confirmation-2024",
                "sample_hash": "f" * 64,
                "role": "confirmation",
                "run_spec_hashes": ["c" * 64],
            },
        ],
        "comparisons": [{
            "comparison_id": "main-comparison",
            "members": [
                {
                    "run_spec_hash": "a" * 64,
                    "trial_role": "candidate",
                },
                {
                    "run_spec_hash": "b" * 64,
                    "trial_role": "candidate",
                },
                {
                    "run_spec_hash": "c" * 64,
                    "trial_role": "candidate",
                },
            ],
        }],
    })
    return value


def initialize_branch(path, plan_hash: str) -> None:
    with connect_sqlite(path) as conn:
        create_instance_branch_schema(conn)
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
                current_trial_plan_hash, created_at, updated_at
            ) VALUES (
                'branch-1', 'instance-1', 'primary', 'validation_design',
                'running', '{}', '', ?, 1, 1
            )
            """,
            (plan_hash,),
        )


def initialize_graph_version(path) -> None:
    graph = {
        "graph_id": "factor-research",
        "version": 1,
        "lifecycle": "active",
        "content_hash": "c" * 64,
        "entry_node": "validation_design",
        "nodes": [
            {
                "node_id": "validation_design",
                "kind": "research",
                "required_capabilities": [],
            },
            {
                "node_id": "diagnostics",
                "kind": "research",
                "required_capabilities": [],
            },
            {
                "node_id": "result",
                "kind": "research",
                "required_capabilities": [],
            },
            {
                "node_id": "factor_improvement",
                "kind": "research",
                "required_capabilities": [],
            },
            {
                "node_id": "hypothesis",
                "kind": "research",
                "required_capabilities": [],
            },
        ],
        "edges": [
            {
                "edge_id": "freeze-plan",
                "from_node": "validation_design",
                "to_node": "diagnostics",
                "guard": {},
                "required_evidence": [],
            },
            {
                "edge_id": "adjudicate-result",
                "from_node": "diagnostics",
                "to_node": "result",
                "guard": {
                    "adjudication_route_bound": True,
                    "factor_revision_authorized": False,
                    "next_trial_stage_required": False,
                },
                "required_evidence": [],
            },
            {
                "edge_id": "advance-stage",
                "from_node": "diagnostics",
                "to_node": "validation_design",
                "guard": {
                    "adjudication_route_bound": True,
                    "factor_revision_authorized": False,
                    "next_trial_stage_required": True,
                    "trial_stage_advance_authorized": True,
                },
                "required_evidence": [],
            },
            {
                "edge_id": "result-cycle-event",
                "from_node": "result",
                "to_node": "result",
                "guard": {"research_cycle_delta_applied": True},
                "required_evidence": [],
            },
            {
                "edge_id": "start-new-hypothesis",
                "from_node": "factor_improvement",
                "to_node": "hypothesis",
                "guard": {
                    "new_hypothesis_version_recorded": True,
                    "trial_ledger_incremented": True,
                    "holdout_status_recorded": True,
                    "factor_change_retained": True,
                },
                "required_evidence": [],
                "server_action": "start_new_hypothesis_lineage",
            },
            {
                "edge_id": "hypothesis-to-validation",
                "from_node": "hypothesis",
                "to_node": "validation_design",
                "guard": {},
                "required_evidence": [],
            },
        ],
    }
    with connect_sqlite(path) as conn:
        conn.execute(
            """
            CREATE TABLE research_graph_versions (
                graph_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                lifecycle TEXT NOT NULL,
                parent_version INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                graph_json TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (graph_id, version)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO research_graph_versions VALUES (
                'factor-research', 1, 'active', 0, ?, ?, 'curator', 1
            )
            """,
            (semantic_hash(graph), orjson.dumps(graph).decode()),
        )


def trial_binding(plan: dict) -> dict:
    return {
        "instance_id": "instance-1",
        "branch_id": "branch-1",
        "trial_plan": plan,
        "trial_plan_hash": trial_plan_hash(plan),
        "trial_plan_version": 1,
        "trial_role": "selection",
        "comparison_id": "main-comparison",
    }


def job_record(
    run_id: str,
    run_spec_value: dict,
    job_id: str = "job-1",
) -> JobRecord:
    return JobRecord(
        job_id=job_id,
        run_id=run_id,
        owner="alice",
        workspace_id="workspace-1",
        kind="ic",
        status=JobStatus.SUBMITTED,
        job_spec={"run_spec": run_spec_value},
        run_spec_hash=semantic_hash(run_spec_value),
    )
