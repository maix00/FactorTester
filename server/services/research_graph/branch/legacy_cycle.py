"""Strict empty Research Cycle bootstrap for replayable pre-cycle branches."""

from __future__ import annotations

import sqlite3
from typing import Any

import orjson

from server.services.research_graph.branch.research_cycle import (
    checkpoint_from_branch_row,
)
from server.services.research_graph.protocol import json_hash
from server.services.research_graph.research_cycle.replay import (
    validate_research_cycle_checkpoint,
)
from .capability_detour.state import DETOUR_NODES

POLICY_REF = "legacy-empty-cycle-bootstrap@1"
PRE_TRIAL_NODES = frozenset({
    "hypothesis_preregistration",
    "data_contract",
    "factor_semantics",
    "validation_design",
})

def continuation_checkpoint(
    conn: sqlite3.Connection,
    *,
    source: sqlite3.Row,
    source_graph: dict[str, Any],
    capability_detour: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    inherited = checkpoint_from_branch_row(source)
    if inherited is not None:
        return inherited, None
    rows = _validate_legacy_source(
        conn,
        source=source,
        graph=source_graph,
        detour=capability_detour,
    )
    identity = {
        "policy_ref": POLICY_REF,
        "owner": str(source["owner"]),
        "graph_id": str(source["graph_id"]),
        "graph_version": int(source["graph_version"]),
        "graph_hash": str(source_graph.get("content_hash") or ""),
        "instance_id": str(source["instance_id"]),
        "branch_id": str(source["branch_id"]),
        "source_trace_id": str(source["latest_trace_id"]),
        "resume_node": str(capability_detour["resume_node"]),
    }
    checkpoint = validate_research_cycle_checkpoint({
        "schema_version": 1,
        "contract_hash": json_hash(identity),
        "trial_plan_hash": "",
        "methodology_hash": json_hash({"policy_ref": POLICY_REF}),
        "claims": [],
        "obligations": [],
        "pending_adjudications": [],
        "pending_closure": None,
        "closure": None,
    })
    descriptor = {
        "schema_version": 1,
        "mode": "legacy_empty_pretrial",
        "reason": "source_predates_research_cycle_without_trial_state",
        "policy_ref": POLICY_REF,
        "source_identity_hash": json_hash(identity),
        "source_trace_id": str(source["latest_trace_id"]),
        "source_trace_count": len(rows),
        "resume_node": str(capability_detour["resume_node"]),
    }
    return checkpoint, descriptor


def _validate_legacy_source(
    conn: sqlite3.Connection,
    *,
    source: sqlite3.Row,
    graph: dict[str, Any],
    detour: dict[str, Any] | None,
) -> list[sqlite3.Row]:
    if int(graph.get("schema_version") or 1) >= 2:
        raise ValueError("legacy cycle bootstrap requires a schema-v1 source")
    if (
        detour is None
        or str(detour.get("resume_node") or "") not in PRE_TRIAL_NODES
        or str(source["current_node"]) not in DETOUR_NODES
    ):
        raise ValueError("legacy cycle bootstrap requires a pre-trial detour")
    if str(source["current_trial_plan_hash"] or ""):
        raise ValueError("legacy cycle bootstrap requires an empty TrialPlan")
    try:
        stage = orjson.loads(source["trial_stage_projection_json"] or "{}")
    except orjson.JSONDecodeError as exc:
        raise ValueError("legacy trial-stage projection is invalid") from exc
    if stage:
        raise ValueError("legacy cycle bootstrap requires no trial stage")
    rows = conn.execute(
        """
        SELECT trace_id, edge_id, from_node, to_node, evidence_json
        FROM research_graph_trace
        WHERE instance_id=? AND branch_id=?
        ORDER BY created_at, rowid
        """,
        (source["instance_id"], source["branch_id"]),
    ).fetchall()
    _replay_topology(rows, source=source, graph=graph)
    return rows


def _replay_topology(
    rows: list[sqlite3.Row],
    *,
    source: sqlite3.Row,
    graph: dict[str, Any],
) -> None:
    edges = {
        str(edge.get("edge_id") or ""): edge
        for edge in graph.get("edges") or []
    }
    current = str(graph.get("entry_node") or "")
    for row in rows:
        try:
            evidence = orjson.loads(row["evidence_json"] or "{}")
        except orjson.JSONDecodeError as exc:
            raise ValueError("legacy trace evidence is invalid") from exc
        if not isinstance(evidence, dict) or any(
            key in evidence
            for key in ("research_cycle", "research_cycle_checkpoint",
                        "claims", "obligations", "trial_plan")
        ):
            raise ValueError("legacy source is not an empty pre-cycle trace")
        edge = edges.get(str(row["edge_id"] or ""))
        if (
            edge is None
            or str(row["from_node"] or "") != current
            or str(edge.get("from_node") or "") not in {current, "*"}
            or str(edge.get("to_node") or "") != str(row["to_node"] or "")
        ):
            raise ValueError("legacy source trace cannot be replayed")
        current = str(row["to_node"] or "")
    if (
        not rows
        or str(rows[-1]["trace_id"]) != str(source["latest_trace_id"])
        or current != str(source["current_node"])
    ):
        raise ValueError("legacy source trace is incomplete")
