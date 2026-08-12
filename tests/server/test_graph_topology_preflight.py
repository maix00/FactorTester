from __future__ import annotations

import sqlite3

import pytest

from server.services.research_graph.branch.topology_preflight import (
    assess_topology_continuation,
    load_work_package_trace_footprint,
    require_topology_continuation,
)


def _graph(*, include_method_node: bool = True) -> dict:
    nodes = [
        {
            "node_id": "factor_semantics",
            "stage": "validation",
            "purpose": "Reconcile factor semantics.",
        },
        {
            "node_id": "validation_design",
            "stage": "validation",
            "purpose": "Freeze the validation design.",
        },
    ]
    edges = [{
        "edge_id": "factor_semantics__validation_design",
        "from_node": "factor_semantics",
        "to_node": "validation_design",
        "edge_type": "conditional",
    }]
    if include_method_node:
        nodes.append({
            "node_id": "cheap_factor_diagnostics",
            "stage": "analysis",
            "purpose": "Run fixed diagnostics.",
        })
        edges.append({
            "edge_id": "validation_design__cheap_diagnostics",
            "from_node": "validation_design",
            "to_node": "cheap_factor_diagnostics",
            "edge_type": "conditional",
        })
    return {"content_hash": "1" * 64, "nodes": nodes, "edges": edges}


def test_preflight_allows_deleting_an_unvisited_method_node() -> None:
    source = _graph()
    target = _graph(include_method_node=False)
    target["content_hash"] = "2" * 64

    result = assess_topology_continuation(
        source_graph=source,
        target_graph=target,
        current_node="validation_design",
        footprint={
            "node_ids": ["factor_semantics", "validation_design"],
            "edge_ids": ["factor_semantics__validation_design"],
        },
    )

    assert result["eligible"] is True
    assert result["reason"] == "compatible_reentry"


def test_preflight_rejects_a_deleted_visited_method_node() -> None:
    result = assess_topology_continuation(
        source_graph=_graph(),
        target_graph=_graph(include_method_node=False),
        current_node="cheap_factor_diagnostics",
        footprint={
            "node_ids": ["validation_design", "cheap_factor_diagnostics"],
            "edge_ids": ["validation_design__cheap_diagnostics"],
        },
    )

    assert result["eligible"] is False
    with pytest.raises(ValueError, match="audited topology mapping"):
        require_topology_continuation(result)


def test_preflight_rejects_a_redefined_visited_edge() -> None:
    source = _graph(include_method_node=False)
    target = _graph(include_method_node=False)
    target["edges"][0]["to_node"] = "factor_semantics"

    result = assess_topology_continuation(
        source_graph=source,
        target_graph=target,
        current_node="validation_design",
        footprint={
            "node_ids": ["factor_semantics", "validation_design"],
            "edge_ids": ["factor_semantics__validation_design"],
        },
    )

    assert result["redefined_edges"] == [
        "factor_semantics__validation_design"
    ]
    assert result["eligible"] is False


def test_trace_footprint_uses_all_work_package_incarnations() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE research_graph_instances (
            instance_id TEXT PRIMARY KEY,
            work_package_id TEXT NOT NULL,
            owner TEXT NOT NULL
        );
        CREATE TABLE research_graph_trace (
            trace_id TEXT PRIMARY KEY,
            instance_id TEXT NOT NULL,
            edge_id TEXT NOT NULL,
            from_node TEXT NOT NULL,
            to_node TEXT NOT NULL
        );
        INSERT INTO research_graph_instances VALUES ('i1', 'wp1', 'alice');
        INSERT INTO research_graph_instances VALUES ('i2', 'wp1', 'alice');
        INSERT INTO research_graph_instances VALUES ('i3', 'wp2', 'alice');
        INSERT INTO research_graph_trace VALUES (
            't1', 'i1', 'edge-a', 'node-a', 'node-b'
        );
        INSERT INTO research_graph_trace VALUES (
            't2', 'i2', 'edge-b', 'node-b', 'node-c'
        );
        INSERT INTO research_graph_trace VALUES (
            't3', 'i3', 'edge-x', 'node-x', 'node-y'
        );
        """
    )

    footprint = load_work_package_trace_footprint(
        conn,
        owner="alice",
        work_package_id="wp1",
    )

    assert footprint == {
        "edge_ids": ["edge-a", "edge-b"],
        "node_ids": ["node-a", "node-b", "node-c"],
    }
