"""Read and write the server's current Research Graph version."""

from __future__ import annotations

from copy import deepcopy
import time
from typing import Any

import settings as Settings
from server.services.research_graph.versions import load_graph_from_conn
from tools.data.sqlite.db import connect_sqlite


def load_active_graph(
    *,
    graph_id: str,
    locale: str | None = None,
) -> dict[str, Any] | None:
    """Load the version currently selected for a Graph id."""
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT version, activated_by, activated_at
            FROM active_research_graphs
            WHERE graph_id=?
            """,
            (graph_id,),
        ).fetchone()
        if row is None:
            return None
        graph = load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=int(row["version"]),
        )
    if graph is None:
        raise ValueError("active pointer references a missing Graph version")
    value = _with_pointer(graph, row)
    if locale is None:
        return value
    from server.services.research_graph.presentations import attach_presentation

    return attach_presentation(value, locale=locale)


def activate_graph(
    *,
    graph_id: str,
    source_version: int,
    actor: str,
) -> dict[str, Any]:
    """Select an already registered version immediately.

    Graph publication has one small server-side boundary: the version must
    already pass the normal YAML/Graph schema validator.  There is no proposal,
    reviewer, token quota, human-authorization, or activation-gate workflow.
    """
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        source = load_graph_from_conn(
            conn,
            graph_id=graph_id,
            version=source_version,
        )
        if source is None:
            raise KeyError("graph version not found")
        conn.execute(
            """
            INSERT INTO active_research_graphs (
                graph_id, version, activated_by, activated_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(graph_id) DO UPDATE SET
                version=excluded.version,
                activated_by=excluded.activated_by,
                activated_at=excluded.activated_at
            """,
            (graph_id, int(source_version), actor, now),
        )
    return _with_pointer(
        source,
        {
            "version": int(source_version),
            "activated_by": actor,
            "activated_at": now,
        },
    )


def _with_pointer(
    graph: dict[str, Any],
    pointer: Any,
) -> dict[str, Any]:
    value = deepcopy(graph)
    value["active_pointer"] = {
        "version": int(pointer["version"]),
        "activated_by": str(pointer["activated_by"]),
        "activated_at": float(pointer["activated_at"]),
    }
    value["is_active"] = True
    return value
