"""Human-only, node-scoped downgrade for incomplete coverage gates."""

from __future__ import annotations

import sqlite3
import time
from typing import Any

import settings as Settings
from tools.data.sqlite.db import connect_sqlite


def create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS research_human_gate_overrides (
            owner TEXT NOT NULL,
            instance_id TEXT NOT NULL,
            branch_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            checkpoint_ref TEXT NOT NULL,
            enabled INTEGER NOT NULL,
            revision INTEGER NOT NULL,
            authorized_at REAL NOT NULL,
            PRIMARY KEY (owner, instance_id, branch_id)
        )
        """
    )


def set_override(
    conn: sqlite3.Connection,
    *,
    owner: str,
    instance_id: str,
    branch_id: str,
    node_id: str,
    checkpoint_ref: str,
    enabled: bool,
) -> dict[str, Any]:
    create_schema(conn)
    current = conn.execute(
        """
        SELECT revision FROM research_human_gate_overrides
        WHERE owner=? AND instance_id=? AND branch_id=?
        """,
        (owner, instance_id, branch_id),
    ).fetchone()
    revision = int(current["revision"]) + 1 if current is not None else 1
    now = time.time()
    conn.execute(
        """
        INSERT INTO research_human_gate_overrides (
            owner, instance_id, branch_id, node_id, checkpoint_ref,
            enabled, revision, authorized_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(owner, instance_id, branch_id) DO UPDATE SET
            node_id=excluded.node_id,
            checkpoint_ref=excluded.checkpoint_ref,
            enabled=excluded.enabled,
            revision=excluded.revision,
            authorized_at=excluded.authorized_at
        """,
        (
            owner, instance_id, branch_id, node_id, checkpoint_ref,
            int(enabled), revision, now,
        ),
    )
    return {
        "enabled": enabled,
        "node_id": node_id,
        "checkpoint_ref": checkpoint_ref,
        "revision": revision,
        "authorized_at": now,
        "scope": "missing_coverage_only",
    }


def current_override(
    conn: sqlite3.Connection,
    *,
    owner: str,
    instance_id: str,
    branch_id: str,
    node_id: str,
    checkpoint_ref: str,
) -> dict[str, Any]:
    create_schema(conn)
    row = conn.execute(
        """
        SELECT node_id, checkpoint_ref, enabled, revision, authorized_at
        FROM research_human_gate_overrides
        WHERE owner=? AND instance_id=? AND branch_id=?
        """,
        (owner, instance_id, branch_id),
    ).fetchone()
    if row is None:
        return _disabled(node_id, checkpoint_ref)
    matches = (
        str(row["node_id"]) == node_id
        and str(row["checkpoint_ref"]) == checkpoint_ref
    )
    return {
        "enabled": bool(row["enabled"]) and matches,
        "node_id": node_id,
        "checkpoint_ref": checkpoint_ref,
        "revision": int(row["revision"]),
        "authorized_at": float(row["authorized_at"]),
        "scope": "missing_coverage_only",
        "stale": not matches,
    }


def override_from_branch_row(
    row: sqlite3.Row,
    *,
    node_id: str,
    checkpoint_ref: str,
) -> dict[str, Any]:
    """Project the joined override without adding a second branch query."""
    columns = set(row.keys())
    stored_node = (
        str(row["human_override_node_id"] or "")
        if "human_override_node_id" in columns else ""
    )
    stored_checkpoint = (
        str(row["human_override_checkpoint_ref"] or "")
        if "human_override_checkpoint_ref" in columns else ""
    )
    if not stored_node:
        return _disabled(node_id, checkpoint_ref)
    matches = stored_node == node_id and stored_checkpoint == checkpoint_ref
    return {
        "enabled": bool(row["human_override_enabled"]) and matches,
        "node_id": node_id,
        "checkpoint_ref": checkpoint_ref,
        "revision": int(row["human_override_revision"] or 0),
        "authorized_at": float(row["human_override_authorized_at"] or 0.0),
        "scope": "missing_coverage_only",
        "stale": not matches,
    }


def _disabled(node_id: str, checkpoint_ref: str) -> dict[str, Any]:
    return {
        "enabled": False,
        "node_id": node_id,
        "checkpoint_ref": checkpoint_ref,
        "revision": 0,
        "authorized_at": 0.0,
        "scope": "missing_coverage_only",
        "stale": False,
    }


def load_for_branch(
    *, owner: str, instance_id: str, branch_id: str,
) -> dict[str, Any]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        create_schema(conn)
        node_id, checkpoint_ref = _branch_identity(
            conn,
            owner=owner,
            instance_id=instance_id,
            branch_id=branch_id,
        )
        return current_override(
            conn,
            owner=owner,
            instance_id=instance_id,
            branch_id=branch_id,
            node_id=node_id,
            checkpoint_ref=checkpoint_ref,
        )


def authorize_for_branch(
    *,
    owner: str,
    instance_id: str,
    branch_id: str,
    expected_node: str,
    expected_checkpoint_ref: str,
    enabled: bool,
) -> dict[str, Any]:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        create_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        node_id, checkpoint_ref = _branch_identity(
            conn,
            owner=owner,
            instance_id=instance_id,
            branch_id=branch_id,
        )
        if node_id != expected_node or checkpoint_ref != expected_checkpoint_ref:
            raise ValueError("human gate override target is stale")
        value = set_override(
            conn,
            owner=owner,
            instance_id=instance_id,
            branch_id=branch_id,
            node_id=node_id,
            checkpoint_ref=checkpoint_ref,
            enabled=enabled,
        )
        conn.commit()
        return value


def _branch_identity(
    conn: sqlite3.Connection,
    *,
    owner: str,
    instance_id: str,
    branch_id: str,
) -> tuple[str, str]:
    row = conn.execute(
        """
        SELECT b.current_node, b.latest_trace_id
        FROM research_graph_instances AS i
        JOIN research_graph_branches AS b ON b.instance_id=i.instance_id
        WHERE i.instance_id=? AND b.branch_id=? AND i.owner=?
        """,
        (instance_id, branch_id, owner),
    ).fetchone()
    if row is None:
        raise KeyError("graph branch not found")
    latest_trace_id = str(row["latest_trace_id"] or "")
    return (
        str(row["current_node"]),
        f"trace:{latest_trace_id}" if latest_trace_id else "",
    )
