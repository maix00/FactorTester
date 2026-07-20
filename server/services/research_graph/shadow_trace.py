"""Bounded Graph-path and Research Cycle shadow replay."""

from __future__ import annotations

import sqlite3
from typing import Any

import orjson

import settings as Settings
from server.services.research_graph.protocol import json_hash
from server.services.research_graph.research_cycle.evidence import (
    validate_agent_evidence_envelope,
)
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
            is_continuation = bootstrap_edge == "__graph_continuation__"
            fork_node = _bootstrap_node(
                evidence,
                graph,
                continuation=is_continuation,
            )
            if (
                (
                    is_continuation
                    and not _continuation_bootstrap_valid(
                        evidence=evidence,
                        graph=graph,
                        runtime=runtime,
                    )
                )
                or
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


def _continuation_bootstrap_valid(
    *,
    evidence: dict[str, Any],
    graph: dict[str, Any],
    runtime: sqlite3.Row,
) -> bool:
    continuation = evidence.get("graph_continuation")
    server_evidence = evidence.get("server_evidence")
    envelope = (
        server_evidence.get("job_attempt")
        if isinstance(server_evidence, dict)
        else None
    )
    if not isinstance(continuation, dict) or not isinstance(envelope, dict):
        return False
    authorization_ref = str(continuation.get("authorization_ref") or "")
    if not authorization_ref.startswith("maintenance-case:"):
        return False
    case_id = authorization_ref.removeprefix("maintenance-case:")
    descriptor = {
        key: value
        for key, value in continuation.items()
        if key != "authorization_ref"
    }
    target_hash = json_hash(descriptor)
    try:
        validated_envelope = validate_agent_evidence_envelope(envelope)
    except ValueError:
        return False
    facts = validated_envelope.get("facts") or {}
    if (
        str(descriptor.get("owner") or "") != str(runtime["owner"])
        or str(descriptor.get("graph_id") or "") != str(runtime["graph_id"])
        or int(descriptor.get("target_graph_version") or 0)
        != int(runtime["graph_version"])
        or str(descriptor.get("target_graph_hash") or "")
        != str(graph.get("content_hash") or "")
        or str(descriptor.get("target_node") or "")
        != str(runtime["current_node"])
        or str(descriptor.get("workspace_id") or "")
        != str(runtime["workspace_id"])
        or str(descriptor.get("job_id") or "")
        != str(facts.get("job_id") or "")
        or str(descriptor.get("job_evidence_hash") or "")
        != str(validated_envelope.get("envelope_hash") or "")
    ):
        return False
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        source = conn.execute(
            """
            SELECT i.graph_id, i.graph_version, i.workspace_id,
                   v.graph_json, b.latest_trace_id,
                   t.evidence_json,
                   g.status AS gate_status,
                   g.affected_refs_json AS gate_affected_refs_json,
                   g.change_refs_json AS gate_change_refs_json,
                   g.latest_result_ref AS gate_latest_result_ref
            FROM research_graph_instances i
            JOIN research_graph_branches b
              ON b.instance_id=i.instance_id
            JOIN research_graph_versions v
              ON v.graph_id=i.graph_id AND v.version=i.graph_version
            JOIN research_graph_trace t ON t.trace_id=b.latest_trace_id
            JOIN research_maintenance_cases g
              ON g.owner_user_id=i.owner
             AND g.case_id=? AND g.kind='approval_gate'
            WHERE i.owner=? AND i.instance_id=? AND b.branch_id=?
            """,
            (
                case_id,
                str(runtime["owner"]),
                str(descriptor.get("source_instance_id") or ""),
                str(descriptor.get("source_branch_id") or ""),
            ),
        ).fetchone()
    if source is None:
        return False
    try:
        source_evidence = orjson.loads(source["evidence_json"])
        source_graph = orjson.loads(source["graph_json"])
        checkpoint = source_evidence["research_cycle_checkpoint"]
        affected_refs = orjson.loads(source["gate_affected_refs_json"])
        change_refs = orjson.loads(source["gate_change_refs_json"])
    except (KeyError, TypeError, orjson.JSONDecodeError):
        return False
    expected_effect = (
        f"graph-continuation:{runtime['instance_id']}:"
        f"{runtime['branch_id']}:{target_hash}"
    )
    return (
        str(source["graph_id"]) == str(descriptor.get("graph_id") or "")
        and int(source["graph_version"])
        == int(descriptor.get("source_graph_version") or 0)
        and str(source["workspace_id"])
        == str(descriptor.get("workspace_id") or "")
        and str(source_graph.get("content_hash") or "")
        == str(descriptor.get("source_graph_hash") or "")
        and str(source["latest_trace_id"])
        == str(descriptor.get("source_trace_id") or "")
        and str(checkpoint.get("projection_hash") or "")
        == str(descriptor.get("source_checkpoint_hash") or "")
        and str(source["gate_status"]) == "resolved"
        and f"gate-action:continue_graph_branch" in affected_refs
        and f"gate-target-hash:{target_hash}" in affected_refs
        and any(
            str(ref).startswith("gate-approval:")
            for ref in change_refs
        )
        and str(source["gate_latest_result_ref"]) == expected_effect
    )


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
