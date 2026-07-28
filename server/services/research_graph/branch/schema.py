"""Target Graph instance, branch, and trace persistence."""

from __future__ import annotations

import json
import sqlite3


def create_instance_branch_schema(conn: sqlite3.Connection) -> None:
    from server.services.research_graph.work_packages import (
        create_schema as create_work_package_schema,
    )

    create_work_package_schema(conn)
    statements = (
        """
        CREATE TABLE IF NOT EXISTS research_graph_instances (
            instance_id TEXT PRIMARY KEY,
            work_package_id TEXT NOT NULL DEFAULT '',
            owner TEXT NOT NULL,
            created_by_profile_ref TEXT NOT NULL DEFAULT '',
            current_owner_profile_ref TEXT NOT NULL DEFAULT '',
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
            hypothesis_branch_id TEXT NOT NULL DEFAULT '',
            is_current_incarnation INTEGER NOT NULL DEFAULT 1,
            instance_id TEXT NOT NULL,
            label TEXT NOT NULL,
            current_node TEXT NOT NULL,
            status TEXT NOT NULL,
            current_capability_resolution_json TEXT NOT NULL,
            current_capability_resolution_hash TEXT NOT NULL,
            current_trial_plan_hash TEXT NOT NULL DEFAULT '',
            trial_stage_projection_json TEXT NOT NULL DEFAULT '{}',
            entry_resolution_frame_json TEXT NOT NULL DEFAULT '{}',
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
            acting_profile_ref TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_research_graph_trace_branch
        ON research_graph_trace(instance_id, branch_id, created_at)
        """,
        """
        CREATE TABLE IF NOT EXISTS research_report_item_checkpoints (
            checkpoint_hash TEXT PRIMARY KEY,
            instance_id TEXT NOT NULL,
            branch_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            fragment_hash TEXT NOT NULL,
            report_items_json TEXT NOT NULL,
            report_artifact_ref TEXT NOT NULL,
            actor TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_report_item_checkpoints_branch_node
        ON research_report_item_checkpoints(
            instance_id, branch_id, node_id, created_at
        )
        """,
    )
    for statement in statements:
        conn.execute(statement)
    from server.services.research_graph.profile_research_projection import (
        ensure_profile_research_indexes,
    )
    ensure_profile_research_indexes(conn)


def ensure_instance_branch_schema(conn: sqlite3.Connection) -> None:
    """Create owners and add the compact stage projection on older targets."""
    create_instance_branch_schema(conn)
    from .checkpoint_schema import migrate_report_checkpoint_receipts

    migrate_report_checkpoint_receipts(conn)
    columns = table_columns(conn, "research_graph_branches")
    instance_columns = table_columns(conn, "research_graph_instances")
    identity_upgrade_required = any((
        "hypothesis_branch_id" not in columns,
        "is_current_incarnation" not in columns,
        "work_package_id" not in instance_columns,
    ))
    if "hypothesis_branch_id" not in columns:
        conn.execute(
            "ALTER TABLE research_graph_branches "
            "ADD COLUMN hypothesis_branch_id TEXT NOT NULL DEFAULT ''"
        )
        conn.execute(
            "UPDATE research_graph_branches "
            "SET hypothesis_branch_id=branch_id "
            "WHERE hypothesis_branch_id=''"
        )
    if "is_current_incarnation" not in columns:
        conn.execute(
            "ALTER TABLE research_graph_branches "
            "ADD COLUMN is_current_incarnation INTEGER NOT NULL DEFAULT 1"
        )
    if "trial_stage_projection_json" not in columns:
        conn.execute(
            "ALTER TABLE research_graph_branches "
            "ADD COLUMN trial_stage_projection_json "
            "TEXT NOT NULL DEFAULT '{}'"
        )
    if "entry_resolution_frame_json" not in columns:
        conn.execute(
            "ALTER TABLE research_graph_branches "
            "ADD COLUMN entry_resolution_frame_json "
            "TEXT NOT NULL DEFAULT '{}'"
        )
    if "work_package_id" not in instance_columns:
        conn.execute(
            "ALTER TABLE research_graph_instances "
            "ADD COLUMN work_package_id TEXT NOT NULL DEFAULT ''"
        )
        conn.execute(
            "UPDATE research_graph_instances "
            "SET work_package_id=instance_id WHERE work_package_id=''"
        )
    if identity_upgrade_required:
        _restore_continuation_identities(conn)
    if "created_by_profile_ref" not in instance_columns:
        conn.execute(
            "ALTER TABLE research_graph_instances "
            "ADD COLUMN created_by_profile_ref TEXT NOT NULL DEFAULT ''"
        )
    if "current_owner_profile_ref" not in instance_columns:
        conn.execute(
            "ALTER TABLE research_graph_instances "
            "ADD COLUMN current_owner_profile_ref TEXT NOT NULL DEFAULT ''"
        )
    trace_columns = table_columns(conn, "research_graph_trace")
    if "acting_profile_ref" not in trace_columns:
        conn.execute(
            "ALTER TABLE research_graph_trace "
            "ADD COLUMN acting_profile_ref TEXT NOT NULL DEFAULT ''"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS "
        "idx_research_graph_instances_profile_owner "
        "ON research_graph_instances(owner, current_owner_profile_ref, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS "
        "idx_research_graph_instances_work_package "
        "ON research_graph_instances(owner, workspace_id, work_package_id, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS "
        "idx_research_graph_branches_hypothesis "
        "ON research_graph_branches(hypothesis_branch_id, updated_at)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "idx_research_graph_branches_current_incarnation "
        "ON research_graph_branches(hypothesis_branch_id) "
        "WHERE is_current_incarnation=1 AND hypothesis_branch_id<>''"
    )
    from server.services.research_graph.work_packages import backfill

    backfill(conn)


def _restore_continuation_identities(conn: sqlite3.Connection) -> None:
    """Restore logical identity from strict, immutable continuation edges."""
    branch_scopes = {
        (str(row["instance_id"]), str(row["branch_id"])): (
            str(row["owner"]),
            str(row["workspace_id"]),
            str(row["graph_id"]),
        )
        for row in conn.execute(
            """
            SELECT i.instance_id, b.branch_id,
                   i.owner, i.workspace_id, i.graph_id
            FROM research_graph_instances AS i
            JOIN research_graph_branches AS b
              ON b.instance_id=i.instance_id
            """
        ).fetchall()
    }
    rows = conn.execute(
        """
        SELECT t.trace_id, t.instance_id, t.branch_id, t.evidence_json
        FROM research_graph_trace AS t
        WHERE t.edge_id='__graph_continuation__'
        ORDER BY t.created_at, t.trace_id
        """
    ).fetchall()
    # The source depends on the descriptor, so validate it explicitly below.
    edges: dict[tuple[str, str], tuple[str, str]] = {}
    sources: set[tuple[str, str]] = set()
    for row in rows:
        try:
            evidence = json.loads(str(row["evidence_json"] or "{}"))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"continuation trace {row['trace_id']} has invalid evidence"
            ) from exc
        descriptor = evidence.get("graph_continuation")
        if not isinstance(descriptor, dict):
            raise ValueError(
                f"continuation trace {row['trace_id']} lacks descriptor"
            )
        source = (
            str(descriptor.get("source_instance_id") or ""),
            str(descriptor.get("source_branch_id") or ""),
        )
        target = (str(row["instance_id"]), str(row["branch_id"]))
        if not all(source) or source == target:
            raise ValueError("continuation identity is invalid")
        source_scope = branch_scopes.get(source)
        target_scope = branch_scopes.get(target)
        if source_scope is None or target_scope is None:
            raise ValueError("continuation identity references a missing branch")
        if source_scope != target_scope:
            raise ValueError("continuation crosses owner, workspace, or graph")
        if target in edges or source in sources:
            raise ValueError("continuation identity is ambiguous")
        edges[target] = source
        sources.add(source)

    def root(node: tuple[str, str]) -> tuple[str, str]:
        seen: set[tuple[str, str]] = set()
        while node in edges:
            if node in seen:
                raise ValueError("continuation identity contains a cycle")
            seen.add(node)
            node = edges[node]
        return node

    conn.execute(
        "UPDATE research_graph_instances SET work_package_id=instance_id"
    )
    conn.execute(
        """
        UPDATE research_graph_branches
        SET hypothesis_branch_id=branch_id, is_current_incarnation=1
        """
    )
    for target, source in edges.items():
        root_instance_id, root_branch_id = root(target)
        conn.execute(
            "UPDATE research_graph_instances SET work_package_id=? "
            "WHERE instance_id=?",
            (root_instance_id, target[0]),
        )
        conn.execute(
            "UPDATE research_graph_branches SET hypothesis_branch_id=? "
            "WHERE instance_id=? AND branch_id=?",
            (root_branch_id, *target),
        )
        conn.execute(
            "UPDATE research_graph_branches SET is_current_incarnation=0 "
            "WHERE instance_id=? AND branch_id=?",
            source,
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
