"""Bounded Graph-path and Research Cycle shadow replay."""

from __future__ import annotations

import sqlite3
from typing import Any

import orjson

import settings as Settings
from server.services.research_graph.protocol import json_hash
from server.services.research_graph.research_cycle.trace_replay import (
    verify_research_cycle_trace,
)
from tools.data.sqlite.db import connect_sqlite


MAX_REPLAY_ROWS = 1000


def replay_shadow_trace(
    *,
    graph: dict[str, Any],
    runtime: sqlite3.Row,
) -> dict[str, Any]:
    """Replay one bounded branch without mutating execution history."""
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT trace_id, edge_id, from_node, to_node, evidence_json
            FROM research_graph_trace
            WHERE instance_id=? AND branch_id=?
            ORDER BY created_at, trace_id
            LIMIT ?
            """,
            (
                str(runtime["instance_id"]),
                str(runtime["branch_id"]),
                MAX_REPLAY_ROWS + 1,
            ),
        ).fetchall()
    if len(rows) > MAX_REPLAY_ROWS:
        raise ValueError("shadow replay trace exceeds bounded comparison rows")
    edges = {
        str(edge["edge_id"]): edge for edge in graph.get("edges") or []
    }
    current = str(
        graph.get("entry_node")
        or ((graph.get("nodes") or [{}])[0].get("node_id") or "")
    )
    if not current:
        raise ValueError("shadow Graph entry node is invalid")
    evidence_count = 0
    path: list[str] = []
    cycle_checkpoint: dict[str, Any] | None = None
    previous_trace_id = ""
    for row in rows:
        evidence = orjson.loads(row["evidence_json"])
        if not isinstance(evidence, dict):
            return _summary(
                current=current,
                expected=str(runtime["current_node"]),
                path=path,
                evidence_count=evidence_count,
                status="invalid",
            )
        bootstrap_edge = str(row["edge_id"])
        if bootstrap_edge in {
            "__branch_fork__",
            "__graph_continuation__",
        }:
            fork_node = _bootstrap_node(
                evidence,
                graph,
                continuation=(
                    bootstrap_edge == "__graph_continuation__"
                ),
            )
            if (
                path
                or previous_trace_id
                or str(row["from_node"]) != fork_node
                or str(row["to_node"]) != fork_node
            ):
                return _summary(
                    current=current,
                    expected=str(runtime["current_node"]),
                    path=path,
                    evidence_count=evidence_count,
                    status="invalid",
                )
            cycle_checkpoint = _cycle_from_evidence(
                evidence=evidence,
                previous_checkpoint=None,
                previous_trace_id="",
            )
            if (
                evidence.get("research_cycle") is not None
                and cycle_checkpoint is None
            ):
                return _summary(
                    current=fork_node,
                    expected=str(runtime["current_node"]),
                    path=path,
                    evidence_count=evidence_count,
                    status="invalid",
                )
            current = fork_node
            previous_trace_id = str(row["trace_id"])
            continue
        edge = edges.get(str(row["edge_id"]))
        if (
            edge is None
            or str(row["from_node"]) != current
            or str(edge["from_node"]) not in {current, "*"}
            or str(row["to_node"]) != str(edge["to_node"])
        ):
            return _summary(
                current=current,
                expected=str(runtime["current_node"]),
                path=path,
                evidence_count=evidence_count,
                status="invalid",
            )
        factual = evidence.get("evidence_envelope")
        if isinstance(factual, dict) and factual.get("schema_version") == 2:
            evidence_count += len(factual.get("source_refs") or [])
        if (
            evidence.get("research_cycle") is not None
            or evidence.get("research_cycle_checkpoint") is not None
        ):
            cycle_checkpoint = _cycle_from_evidence(
                evidence=evidence,
                previous_checkpoint=cycle_checkpoint,
                previous_trace_id=previous_trace_id,
            )
            if cycle_checkpoint is None:
                return _summary(
                    current=current,
                    expected=str(runtime["current_node"]),
                    path=path,
                    evidence_count=evidence_count,
                    status="invalid",
                )
        path.append(str(row["edge_id"]))
        current = str(row["to_node"])
        previous_trace_id = str(row["trace_id"])
    latest_matches = (
        (not rows and not str(runtime["latest_trace_id"]))
        or (
            bool(rows)
            and str(rows[-1]["trace_id"]) == str(runtime["latest_trace_id"])
        )
    )
    return _summary(
        current=current,
        expected=str(runtime["current_node"]),
        path=path,
        evidence_count=evidence_count,
        status=(
            "current" if cycle_checkpoint is not None else "uninitialized"
        ),
        passed=current == str(runtime["current_node"]) and latest_matches,
    )


def _bootstrap_node(
    evidence: dict[str, Any],
    graph: dict[str, Any],
    *,
    continuation: bool,
) -> str:
    fork = evidence.get(
        "graph_continuation" if continuation else "branch_fork"
    )
    fork_node = (
        str(
            fork.get("target_node" if continuation else "checkpoint_node")
            or ""
        )
        if isinstance(fork, dict)
        else ""
    )
    declared_nodes = {
        str(item.get("node_id") or "")
        for item in graph.get("nodes") or []
    }
    return fork_node if fork_node in declared_nodes else ""


def _cycle_from_evidence(
    *,
    evidence: dict[str, Any],
    previous_checkpoint: dict[str, Any] | None,
    previous_trace_id: str,
) -> dict[str, Any] | None:
    try:
        return verify_research_cycle_trace(
            previous_checkpoint=previous_checkpoint,
            previous_trace_id=previous_trace_id,
            event=evidence.get("research_cycle"),
            projected_checkpoint=evidence.get(
                "research_cycle_checkpoint"
            ),
        )
    except ValueError:
        return None


def _summary(
    *,
    current: str,
    expected: str,
    path: list[str],
    evidence_count: int,
    status: str,
    passed: bool = False,
) -> dict[str, Any]:
    return {
        "passed": passed,
        "transition_count": len(path),
        "path_hash": json_hash(path),
        "evidence_ref_count": evidence_count,
        "derived_node": current,
        "projected_node": expected,
        "research_cycle_status": status,
    }
