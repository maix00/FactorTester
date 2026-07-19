"""Target Graph instance, branch, and trace persistence."""

from __future__ import annotations

import sqlite3


def create_instance_branch_schema(conn: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE IF NOT EXISTS research_graph_instances (
            instance_id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            graph_id TEXT NOT NULL,
            graph_version INTEGER NOT NULL,
            product_group TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'live',
            shadow_run_id TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_research_graph_instances_owner
        ON research_graph_instances(owner, created_at)
        """,
        """
        CREATE TABLE IF NOT EXISTS research_graph_branches (
            branch_id TEXT PRIMARY KEY,
            instance_id TEXT NOT NULL,
            label TEXT NOT NULL,
            current_node TEXT NOT NULL,
            status TEXT NOT NULL,
            current_capability_resolution_json TEXT NOT NULL,
            current_capability_resolution_hash TEXT NOT NULL,
            current_trial_plan_hash TEXT NOT NULL DEFAULT '',
            trial_stage_projection_json TEXT NOT NULL DEFAULT '{}',
            evidence_refs_json TEXT NOT NULL DEFAULT '[]',
            omitted_evidence_count INTEGER NOT NULL DEFAULT 0,
            latest_trace_id TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_research_graph_branches_instance
        ON research_graph_branches(instance_id, created_at)
        """,
        """
        CREATE TABLE IF NOT EXISTS research_graph_trace (
            trace_id TEXT PRIMARY KEY,
            instance_id TEXT NOT NULL,
            branch_id TEXT NOT NULL,
            edge_id TEXT NOT NULL,
            from_node TEXT NOT NULL,
            to_node TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            telemetry_json TEXT NOT NULL DEFAULT '{}',
            actor TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_research_graph_trace_branch
        ON research_graph_trace(instance_id, branch_id, created_at)
        """,
    )
    for statement in statements:
        conn.execute(statement)


def ensure_instance_branch_schema(conn: sqlite3.Connection) -> None:
    """Create owners and add the compact stage projection on older targets."""
    create_instance_branch_schema(conn)
    columns = table_columns(conn, "research_graph_branches")
    if "trial_stage_projection_json" not in columns:
        conn.execute(
            "ALTER TABLE research_graph_branches "
            "ADD COLUMN trial_stage_projection_json "
            "TEXT NOT NULL DEFAULT '{}'"
        )


def table_columns(
    conn: sqlite3.Connection,
    table: str,
) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def has_batch4_legacy_schema(conn: sqlite3.Connection) -> bool:
    tables = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if not {
        "research_graph_instances",
        "research_graph_branches",
    }.intersection(tables):
        return False
    if {
        "research_graph_node_resolutions",
        "research_capability_receipts",
    }.intersection(tables):
        return True
    instance_columns = table_columns(conn, "research_graph_instances")
    branch_columns = table_columns(conn, "research_graph_branches")
    return bool(
        {"capability_resolution_json", "token_budget"}
        .intersection(instance_columns)
        or "current_capability_resolution_json" not in branch_columns
    )
