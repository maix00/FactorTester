"""Deterministic topology eligibility for explicit Graph continuation."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

import orjson


def load_work_package_trace_footprint(
    conn: sqlite3.Connection,
    *,
    owner: str,
    work_package_id: str,
) -> dict[str, list[str]]:
    """Load accepted transition identities for one Work Package in one query."""
    rows = conn.execute(
        """
        SELECT DISTINCT t.edge_id, t.from_node, t.to_node
        FROM research_graph_trace t
        JOIN research_graph_instances i ON i.instance_id=t.instance_id
        WHERE i.owner=? AND i.work_package_id=?
        """,
        (owner, work_package_id),
    ).fetchall()
    return {
        "edge_ids": sorted({str(row["edge_id"]) for row in rows}),
        "node_ids": sorted({
            str(value)
            for row in rows
            for value in (row["from_node"], row["to_node"])
        }),
    }


def assess_topology_continuation(
    *,
    source_graph: dict[str, Any],
    target_graph: dict[str, Any],
    current_node: str,
    footprint: dict[str, list[str]],
) -> dict[str, Any]:
    """Fail closed when accepted history lacks an exact target topology."""
    source_nodes = _items_by_id(source_graph.get("nodes"), "node_id")
    target_nodes = _items_by_id(target_graph.get("nodes"), "node_id")
    source_edges = _items_by_id(source_graph.get("edges"), "edge_id")
    target_edges = _items_by_id(target_graph.get("edges"), "edge_id")
    visited_nodes = set(footprint.get("node_ids") or []) | {current_node}
    visited_edges = set(footprint.get("edge_ids") or [])
    missing_nodes = sorted(visited_nodes - set(target_nodes))
    missing_edges = sorted(visited_edges - set(target_edges))
    unknown_source_nodes = sorted(visited_nodes - set(source_nodes))
    unknown_source_edges = sorted(visited_edges - set(source_edges))
    redefined_nodes = sorted(
        node_id
        for node_id in visited_nodes & set(source_nodes) & set(target_nodes)
        if _node_identity(source_nodes[node_id]) != _node_identity(target_nodes[node_id])
    )
    redefined_edges = sorted(
        edge_id
        for edge_id in visited_edges & set(source_edges) & set(target_edges)
        if _edge_identity(source_edges[edge_id]) != _edge_identity(target_edges[edge_id])
    )
    failures = {
        "missing_nodes": missing_nodes,
        "missing_edges": missing_edges,
        "unknown_source_nodes": unknown_source_nodes,
        "unknown_source_edges": unknown_source_edges,
        "redefined_nodes": redefined_nodes,
        "redefined_edges": redefined_edges,
    }
    eligible = not any(failures.values())
    identity = {
        "source_graph_hash": str(source_graph.get("content_hash") or ""),
        "target_graph_hash": str(target_graph.get("content_hash") or ""),
        "current_node": current_node,
        "visited_node_ids": sorted(visited_nodes),
        "visited_edge_ids": sorted(visited_edges),
        **failures,
    }
    return {
        "eligible": eligible,
        "reason": "compatible_reentry" if eligible else "topology_mapping_required",
        "footprint_node_count": len(visited_nodes),
        "footprint_edge_count": len(visited_edges),
        **failures,
        "preflight_hash": hashlib.sha256(
            orjson.dumps(identity, option=orjson.OPT_SORT_KEYS)
        ).hexdigest(),
    }


def require_topology_continuation(result: dict[str, Any]) -> None:
    """Raise one bounded error for an ineligible continuation."""
    if result.get("eligible") is True:
        return
    parts = []
    for field in (
        "missing_nodes",
        "missing_edges",
        "unknown_source_nodes",
        "unknown_source_edges",
        "redefined_nodes",
        "redefined_edges",
    ):
        values = result.get(field) or []
        if values:
            parts.append(f"{field}={','.join(values)}")
    raise ValueError(
        "Graph continuation requires an audited topology mapping: "
        + "; ".join(parts)
    )


def _items_by_id(value: Any, field: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        return {}
    return {
        str(item.get(field) or ""): item
        for item in value
        if isinstance(item, dict) and str(item.get(field) or "")
    }


def _node_identity(node: dict[str, Any]) -> bytes:
    return orjson.dumps({
        "node_id": node.get("node_id"),
        "stage": node.get("stage"),
        "purpose": node.get("purpose"),
    }, option=orjson.OPT_SORT_KEYS)


def _edge_identity(edge: dict[str, Any]) -> bytes:
    return orjson.dumps({
        "edge_id": edge.get("edge_id"),
        "from_node": edge.get("from_node"),
        "to_node": edge.get("to_node"),
        "edge_type": edge.get("edge_type"),
        "server_action": edge.get("server_action"),
    }, option=orjson.OPT_SORT_KEYS)
