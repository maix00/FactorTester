"""Transactional eligibility checks for draft Graph shadow instances."""

from __future__ import annotations

import sqlite3
from typing import Any

import orjson

from server.services.research_graph import activation_gate
from server.services.research_graph.protocol import GraphActivationBlocked
from server.services.research_graph.versions import load_graph_from_conn


_UNCONSUMED_GATE_STATUSES = {"claimed", "blocked"}


def require_shadow_eligibility(
    conn: sqlite3.Connection,
    *,
    graph_id: str,
    graph_version: int,
    owner: str,
    proposal_id: str,
) -> tuple[dict[str, Any], int]:
    pointer = conn.execute(
        """
        SELECT version FROM active_research_graphs WHERE graph_id=?
        """,
        (graph_id,),
    ).fetchone()
    if pointer is None:
        raise GraphActivationBlocked("active graph not found")
    active_version = int(pointer["version"])
    target = load_graph_from_conn(
        conn,
        graph_id=graph_id,
        version=graph_version,
    )
    if target is None or target.get("lifecycle") != "draft":
        raise GraphActivationBlocked("shadow draft graph not found")
    if int(target.get("parent_version") or 0) != active_version:
        raise GraphActivationBlocked(
            "shadow graph must be the direct child of the active graph"
        )
    graph_hash = str(target.get("content_hash") or "")

    row = conn.execute(
        """
        SELECT * FROM research_maintenance_cases
        WHERE owner_user_id=? AND case_id=?
        """,
        (owner, proposal_id),
    ).fetchone()
    if row is None:
        raise GraphActivationBlocked("shadow proposal not found")
    case = dict(row)
    case["affected_refs"] = orjson.loads(case["affected_refs_json"])
    case["change_refs"] = orjson.loads(case["change_refs_json"])
    try:
        if str(case["kind"]) != "approval_gate":
            raise ValueError("shadow proposal is not an activation Gate")
        if str(case["status"]) not in _UNCONSUMED_GATE_STATUSES:
            raise ValueError("shadow proposal is not open and unconsumed")
        if activation_gate.gate_action(case) != activation_gate.ACTIVATE_ACTION:
            raise ValueError("shadow proposal action does not match")
        activation_gate.require_graph_target(
            case,
            graph_id=graph_id,
            graph_version=graph_version,
            graph_hash=graph_hash,
        )
    except ValueError as exc:
        raise GraphActivationBlocked(str(exc)) from exc
    return target, active_version
