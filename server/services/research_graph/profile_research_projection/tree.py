"""Git-like bounded checkpoint lineage projection."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.services.research_graph.report_checkpoint import (
    safe_identifier as _safe_identifier,
)

from .refs import research_ref_for
from .summary import _branch_lineage, _json_object

def _tree_projection(
    value: Any,
    branch_rows: list[sqlite3.Row],
) -> dict[str, Any]:
    """Decode the bounded tree carrier and add only authoritative edges.

    Trace rows are the only checkpoint nodes.  The projection never invents a
    merge: ordinary edges connect adjacent loaded checkpoints on one branch;
    fork/continuation edges are emitted only when their creation evidence was
    valid enough for ``_branch_lineage``.
    """
    if value in (None, ""):
        return {"schema_version": 2, "nodes": [], "edges": [],
                "omitted_node_count": 0}
    payload = _json_object(value)
    raw_nodes = payload.get("nodes")
    if not isinstance(raw_nodes, list):
        raw_nodes = []
    branch_by_hypothesis = {
        str(row["hypothesis_branch_id"] or row["branch_id"]): row
        for row in branch_rows
    }
    nodes: list[dict[str, Any]] = []
    by_branch: dict[str, list[dict[str, Any]]] = {}
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            continue
        trace_id = _safe_identifier(raw.get("trace_id"))
        branch_id = _safe_identifier(raw.get("branch_id"))
        hypothesis_branch_id = _safe_identifier(
            raw.get("hypothesis_branch_id")
        ) or branch_id
        edge_id = _safe_identifier(raw.get("edge_id"))
        if not (trace_id and branch_id and hypothesis_branch_id and edge_id):
            continue
        if hypothesis_branch_id not in branch_by_hypothesis:
            # The SQL limits nodes to visible branches.  Keep this guard in
            # case an older cache returns a malformed carrier.
            continue
        try:
            created_at = float(raw.get("created_at"))
            first_rank = int(raw.get("first_rank"))
            last_rank = int(raw.get("last_rank"))
        except (TypeError, ValueError):
            continue
        branch_ref = research_ref_for(
            str(raw.get("instance_id") or ""), branch_id
        )
        graph_id = _safe_identifier(raw.get("graph_id"))
        try:
            graph_version = int(raw.get("graph_version"))
        except (TypeError, ValueError):
            continue
        if not graph_id or graph_version < 1:
            continue
        trace_ref = f"trace:{trace_id}"
        node = {
            "checkpoint_ref": trace_ref,
            "branch_ref": branch_ref,
            # A logical hypothesis can span several physical branches after
            # graph continuation.  Keep ``branch_ref`` as the immutable audit
            # identity, but navigate every incarnation through the current
            # visible branch selected by the Work Package projection.
            "navigation_branch_id": str(
                branch_by_hypothesis[hypothesis_branch_id]["branch_id"]
            ),
            "graph_ref": f"{graph_id}@v{graph_version}",
            "edge_ref": edge_id,
            "from_node": str(raw.get("from_node") or ""),
            "to_node": str(raw.get("to_node") or ""),
            "created_at": created_at,
            "status": (
                str(raw.get("branch_status"))
                if trace_id == str(raw.get("latest_trace_id") or "")
                else "historical"
            ),
            "is_head": trace_id == str(raw.get("latest_trace_id") or ""),
            "is_root": first_rank == 1,
            # Keep ranks private to the projection builder. The public carrier
            # uses checkpoint_ref as the node identity.
            "_sequence_rank": first_rank,
            "_history_rank": last_rank,
            "_instance_id": str(raw.get("instance_id") or ""),
            "_physical_branch_id": branch_id,
        }
        nodes.append(node)
        by_branch.setdefault(hypothesis_branch_id, []).append(node)

    nodes.sort(
        key=lambda item: (item["created_at"], item["checkpoint_ref"])
    )
    edges: list[dict[str, Any]] = []
    for hypothesis_branch_id, branch_nodes in by_branch.items():
        branch_nodes.sort(
            key=lambda item: (
                item["_sequence_rank"], item["checkpoint_ref"]
            )
        )
        current_row = branch_by_hypothesis[hypothesis_branch_id]
        visible_branch_nodes = [
            item for item in branch_nodes
            if item["edge_ref"] != "__graph_continuation__"
        ]
        for previous, current in zip(
            visible_branch_nodes, visible_branch_nodes[1:]
        ):
            hidden_between = [
                item for item in branch_nodes
                if (
                    previous["_sequence_rank"]
                    < item["_sequence_rank"]
                    < current["_sequence_rank"]
                )
            ]
            rank_gap = (
                current["_sequence_rank"] - previous["_sequence_rank"] - 1
            )
            if (
                len(hidden_between) != rank_gap
                or any(
                    item["edge_ref"] != "__graph_continuation__"
                    for item in hidden_between
                )
            ):
                # Root/head windows may omit substantive checkpoints. Never
                # draw a connector over missing research history. Graph
                # continuation receipts are the sole invisible exception:
                # they remain auditable in the report but are not research
                # version-tree nodes.
                continue
            relation = "transition"
            if current["edge_ref"] == "__branch_fork__":
                is_current_lineage = (
                    current["_instance_id"] == str(current_row["instance_id"])
                    and current["_physical_branch_id"]
                    == str(current_row["branch_id"])
                )
                if is_current_lineage:
                    # The authoritative lineage edge below is the connection
                    # for the current incarnation; emitting it here as well
                    # would duplicate the same connector.
                    continue
                # Older physical incarnations remain part of the same logical
                # history. Their creation edge must not disappear merely
                # because a newer continuation is now current.
                relation = "fork"
            edges.append({
                "edge_ref": current["edge_ref"],
                "relation": relation,
                "source_node_ref": previous["checkpoint_ref"],
                "target_node_ref": current["checkpoint_ref"],
                "source_branch_ref": previous["branch_ref"],
                "target_branch_ref": current["branch_ref"],
            })
        row = current_row
        lineage = _branch_lineage(row)
        target = next((item for item in branch_nodes if (
            item["_instance_id"] == str(row["instance_id"])
            and item["_physical_branch_id"] == str(row["branch_id"])
            and item["edge_ref"] == "__branch_fork__"
        )), None)
        if target and lineage.get("relation") == "fork":
            source_branch_ref = lineage.get("source_branch_ref")
            source_trace_ref = lineage.get("source_trace_ref")
            if isinstance(source_branch_ref, str):
                edges.append({
                    "edge_ref": (
                        "lineage:"
                        f"{hypothesis_branch_id}:{target['checkpoint_ref']}"
                    ),
                    "relation": str(lineage["relation"]),
                    "source_node_ref": source_trace_ref or "",
                    "target_node_ref": target["checkpoint_ref"],
                    "source_branch_ref": source_branch_ref,
                    "target_branch_ref": target["branch_ref"],
                })
    public_nodes = [
        {key: value for key, value in node.items() if not key.startswith("_")}
        for node in nodes
        if node["edge_ref"] != "__graph_continuation__"
    ]
    return {
        "schema_version": 2,
        "nodes": public_nodes,
        "edges": edges,
        "omitted_node_count": max(
            int(payload.get("omitted_node_count") or 0), 0
        ),
    }
