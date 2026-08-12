"""Exceptional replacement of a published but unused draft Graph."""

from __future__ import annotations

from typing import Any

import orjson

import settings as Settings
from server.services.research_graph.protocol import validate_graph
from server.services.research_graph.versions import (
    clear_graph_cache_for_current_db,
)
from tools.data.sqlite.db import connect_sqlite


def revise_unused_draft(
    graph: dict[str, Any],
    *,
    actor: str,
) -> dict[str, Any]:
    """Atomically replace a draft that has never entered governance or use."""
    value = validate_graph(graph)
    if value["lifecycle"] != "draft":
        raise ValueError("only a draft Graph may be revised")
    revision = (value.get("change_manifest") or {}).get("draft_revision")
    if not isinstance(revision, dict):
        raise ValueError("draft revision manifest is required")
    expected_hash = str(revision.get("replaces_content_hash") or "")
    if len(expected_hash) != 64:
        raise ValueError("draft revision must bind the replaced content hash")

    graph_id = str(value["graph_id"])
    version = int(value["version"])
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            """
            SELECT lifecycle, content_hash, graph_json, created_by, created_at
            FROM research_graph_versions
            WHERE graph_id=? AND version=?
            """,
            (graph_id, version),
        ).fetchone()
        if current is None:
            raise KeyError("draft graph version not found")
        if str(current["content_hash"]) == value["content_hash"]:
            stored = orjson.loads(current["graph_json"])
            stored["created_by"] = str(current["created_by"])
            stored["created_at"] = float(current["created_at"])
            return stored
        if str(current["lifecycle"]) != "draft":
            raise ValueError("only a draft Graph may be revised")
        if str(current["content_hash"]) != expected_hash:
            raise ValueError("draft revision source hash does not match")
        _require_unused(conn, graph_id=graph_id, version=version)
        created_at = float(current["created_at"])
        conn.execute(
            """
            UPDATE research_graph_versions
            SET content_hash=?, graph_json=?, created_by=?
            WHERE graph_id=? AND version=? AND content_hash=?
            """,
            (
                value["content_hash"],
                orjson.dumps(
                    value,
                    option=orjson.OPT_SORT_KEYS,
                ).decode(),
                actor,
                graph_id,
                version,
                expected_hash,
            ),
        )
    clear_graph_cache_for_current_db()
    return {
        **value,
        "created_by": actor,
        "created_at": created_at,
    }


def _require_unused(conn, *, graph_id: str, version: int) -> None:
    active = conn.execute(
        "SELECT 1 FROM active_research_graphs WHERE graph_id=? AND version=?",
        (graph_id, version),
    ).fetchone()
    instances = conn.execute(
        """
        SELECT 1 FROM research_graph_instances
        WHERE graph_id=? AND graph_version=? LIMIT 1
        """,
        (graph_id, version),
    ).fetchone()
    proposal_prefix = f"graph-proposal:{graph_id}@{version}:"
    governance = conn.execute(
        """
        SELECT 1 FROM research_maintenance_cases
        WHERE kind='approval_gate' AND affected_refs_json LIKE ?
        LIMIT 1
        """,
        (f"%{proposal_prefix}%",),
    ).fetchone()
    if active or instances or governance:
        raise ValueError(
            "draft Graph is immutable after activation, instance creation, "
            "or governance proposal"
        )
