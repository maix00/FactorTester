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
        return requirement_detail(
            graph=graph,
            node=node,
            checkpoint=checkpoint_from_branch_row(row),
            requirement_id=requirement_id,
        )
