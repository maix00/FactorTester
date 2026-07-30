"""Authorized lazy reads for one active Graph requirement contract."""

from __future__ import annotations

from contextlib import closing
from typing import Any

import settings as Settings
from server.services.research_graph.branch.entry_requirements import (
    requirement_detail,
)
from server.services.research_graph.branch.repository import (
    load_instance_branch_with_latest_trace,
)
from server.services.research_graph.branch.research_cycle import (
    checkpoint_from_branch_row,
)
from server.services.research_graph.versions import load_graph_from_conn
from tools.data.sqlite.db import connect_sqlite


def load_current_graph_requirement(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
    requirement_id: str,
) -> dict[str, Any]:
    """Return one current-node contract; never expose the whole catalog."""
    with closing(connect_sqlite(Settings.CACHE_DB_PATH)) as conn:
        row = load_instance_branch_with_latest_trace(
            conn,
            instance_id=instance_id,
            branch_id=branch_id,
            owner=owner,
        )
        if row is None:
            raise KeyError("graph branch not found")
        graph = load_graph_from_conn(
            conn,
            graph_id=str(row["graph_id"]),
            version=int(row["graph_version"]),
        ) or {}
        node = next(
            (
                item
                for item in graph.get("nodes") or []
                if str(item.get("node_id") or "")
                == str(row["current_node"])
            ),
            None,
        )
        if node is None:
            raise ValueError("current graph node is missing")
        entry_ids = {
            str(item) for item in node.get("entry_requirement_refs") or []
        }
        edge_ids = _outgoing_edge_requirement_ids(
            graph, str(node.get("node_id") or "")
        )
        sources = [
            source for source, values in (
                ("entry", entry_ids),
                ("edge", edge_ids),
            )
            if requirement_id in values
        ]
        return requirement_detail(
            graph=graph,
            node=node,
            checkpoint=checkpoint_from_branch_row(row),
            requirement_id=requirement_id,
            allowed_requirement_ids=entry_ids | edge_ids,
            requirement_sources=sources,
        )


def _outgoing_edge_requirement_ids(
    graph: dict[str, Any],
    node_id: str,
) -> set[str]:
    report_requirements = {
        str(item.get("report_requirement_id") or ""): item
        for item in graph.get("report_requirements") or []
        if isinstance(item, dict)
    }
    result: set[str] = set()
    for edge in graph.get("edges") or []:
        if (
            not isinstance(edge, dict)
            or str(edge.get("from_node") or "") != node_id
        ):
            continue
        explicit = {
            str(item) for item in edge.get("obligation_requirement_refs") or []
            if str(item)
        }
        if explicit:
            result.update(explicit)
            continue
        for report_ref in edge.get("report_requirement_refs") or []:
            report = report_requirements.get(str(report_ref)) or {}
            requirement_ref = str(report.get("requirement_ref") or "")
            if requirement_ref.startswith("requirement:"):
                result.add(requirement_ref.removeprefix("requirement:"))
    return result
