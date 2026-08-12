"""Deterministic lineage projection for cross-version continuation."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.services.research_graph.protocol import json_hash
from server.services.research_graph.versions import load_graph_from_conn


_MAX_LINEAGE_DEPTH = 128


def load_descendant_lineage(
    conn: sqlite3.Connection,
    *,
    graph_id: str,
    source_version: int,
    target_version: int,
) -> list[dict[str, Any]]:
    """Return source-to-target Graphs or reject a cross-branch target."""
    if int(source_version) == int(target_version):
        raise ValueError("Graph continuation target is already in use")
    reversed_lineage: list[dict[str, Any]] = []
    seen: set[int] = set()
    cursor = int(target_version)
    while len(reversed_lineage) < _MAX_LINEAGE_DEPTH:
        if cursor in seen:
            raise ValueError("Graph continuation lineage contains a cycle")
        seen.add(cursor)
        graph = load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=cursor,
        )
        if graph is None:
            raise KeyError("Graph continuation lineage version not found")
        reversed_lineage.append(graph)
        if cursor == int(source_version):
            return list(reversed(reversed_lineage))
        parent = int(graph.get("parent_version") or 0)
        if parent < 1:
            break
        cursor = parent
    raise ValueError(
        "Graph continuation target is not a descendant of the source"
    )


def continuation_lineage_projection(
    lineage: list[dict[str, Any]],
) -> dict[str, Any]:
    """Bind the complete immutable path and its cumulative change manifests."""
    if len(lineage) < 2:
        raise ValueError("Graph continuation lineage requires two versions")
    versions = [int(graph["version"]) for graph in lineage]
    hashes = [str(graph["content_hash"]) for graph in lineage]
    manifests = [
        {
            "version": int(graph["version"]),
            "graph_hash": str(graph["content_hash"]),
            "manifest_hash": json_hash(graph.get("change_manifest") or {}),
            "change_ids": [
                str(change.get("change_id") or "")
                for change in (
                    (graph.get("change_manifest") or {}).get("changes") or []
                )
                if str(change.get("change_id") or "")
            ],
        }
        for graph in lineage[1:]
    ]
    identity = {
        "lineage_versions": versions,
        "lineage_graph_hashes": hashes,
        "cumulative_change_manifests": manifests,
    }
    return {
        **identity,
        "lineage_path_hash": json_hash({
            "versions": versions,
            "graph_hashes": hashes,
        }),
        "cumulative_change_manifest_hash": json_hash(manifests),
    }
