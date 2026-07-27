"""Atomic Batch 4 migration into branch-owned current projections."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import sqlite3
import time
from typing import Any

import orjson

from server.services.research_graph.branch.projection import (
    serialize_capability_resolution,
    validate_trial_plan_hash,
)
from server.services.research_graph.branch.schema import (
    create_instance_branch_schema,
    table_columns,
)
from tools.data.sqlite.db import connect_sqlite


_LEGACY_TABLES = {
    "research_graph_instances",
    "research_graph_branches",
    "research_graph_node_resolutions",
    "research_capability_receipts",
    "research_graph_trace",
}
_RESOURCE_COLUMNS = {
    "cumulative_input_tokens",
    "cumulative_output_tokens",
    "cumulative_cache_read_tokens",
    "cumulative_skill_document_tokens",
    "cumulative_artifact_summary_tokens",
    "cumulative_reviewer_tokens",
    "skill_document_load_count",
    "skill_context_cache_hits",
    "trace_count",
    "aggregate_version",
}


def migrate_graph_branch_projection(
    *,
    db_path: str | Path,
    failure_injector: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Project current state once, rebuild owners, and drop duplicate tables."""
    started = time.perf_counter()
    with connect_sqlite(Path(db_path)) as conn:
        tables = _table_names(conn)
        if "research_graph_instances" not in tables:
            return _empty_report(started, len(tables))
        if _is_target_schema(conn, tables):
            return _empty_report(started, len(tables))
        missing = _LEGACY_TABLES - tables
        if missing:
            raise ValueError(
                "legacy Graph branch schema is incomplete: "
                + ", ".join(sorted(missing))
            )
        before_count = len(tables)
        conn.execute("BEGIN IMMEDIATE")
        try:
            instances = _project_instances(conn)
            branches = _project_branches(conn)
            resolution_rows = _count_rows(
                conn,
                "research_graph_node_resolutions",
            )
            receipt_rows = _count_rows(
                conn,
                "research_capability_receipts",
            )
            resource_totals = _resource_totals(conn)
            if failure_injector is not None:
                failure_injector("after_projection")
            conn.execute(
                "DROP INDEX IF EXISTS idx_research_graph_instances_owner"
            )
            conn.execute(
                "DROP INDEX IF EXISTS idx_research_graph_branches_instance"
            )
            conn.execute(
                "ALTER TABLE research_graph_instances "
                "RENAME TO legacy_research_graph_instances"
            )
            conn.execute(
                "ALTER TABLE research_graph_branches "
                "RENAME TO legacy_research_graph_branches"
            )
            create_instance_branch_schema(conn)
            _write_instances(conn, instances)
            # The target schema is created while the legacy instance table is
            # temporarily renamed, so its first backfill sees no instances.
            # Re-run it after projection to retain one canonical Work Package
            # row for every migrated graph instance.
            from server.services.research_graph.work_packages import backfill

            backfill(conn, ensure_title_column=False)
            _write_branches(conn, branches)
            if failure_injector is not None:
                failure_injector("after_target_write")
            conn.execute("DROP TABLE research_graph_node_resolutions")
            conn.execute("DROP TABLE research_capability_receipts")
            conn.execute("DROP TABLE legacy_research_graph_branches")
            conn.execute("DROP TABLE legacy_research_graph_instances")
            if failure_injector is not None:
                failure_injector("after_legacy_drop")
            _validate_target(conn, instances, branches)
            after_count = len(_table_names(conn))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {
        "instances_migrated": len(instances),
        "branches_migrated": len(branches),
        "node_resolution_rows_projected": resolution_rows,
        "capability_receipt_rows_dropped": receipt_rows,
        "resource_aggregate_totals_discarded": resource_totals,
        "schema_tables_before": before_count,
        "schema_tables_after": after_count,
        # The two legacy instance tables are renamed before the target
        # tables are created, so a table-count delta is not a stable removal
        # metric once Work Package support tables are present.  Report the
        # duplicate legacy resource tables actually dropped instead.
        "schema_tables_removed": len({
            "research_graph_node_resolutions",
            "research_capability_receipts",
        } & tables),
        "transactions": 1,
        "rollback_target": (
            "restore pre-migration database backup and parent commit 3045e844"
        ),
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def _project_instances(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        {
            "instance_id": row["instance_id"],
            "work_package_id": row["instance_id"],
            **{
                key: row[key]
                for key in (
                    "owner", "graph_id", "graph_version",
                    "product_group", "workspace_id", "mode",
                    "shadow_run_id", "created_at",
                )
            },
        }
        for row in conn.execute(
            "SELECT * FROM research_graph_instances ORDER BY created_at"
        ).fetchall()
    ]


def _project_branches(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    resolution_rows = conn.execute(
        """
        SELECT instance_id, branch_id, node_id, resolution_json
        FROM research_graph_node_resolutions
        """
    ).fetchall()
    resolutions = {
        (
            str(row["instance_id"]),
            str(row["branch_id"]),
            str(row["node_id"]),
        ): orjson.loads(row["resolution_json"])
        for row in resolution_rows
    }
    instance_fallbacks = {
        str(row["instance_id"]): orjson.loads(
            str(row["capability_resolution_json"] or "{}")
        )
        for row in conn.execute(
            """
            SELECT instance_id, capability_resolution_json
            FROM research_graph_instances
            """
        ).fetchall()
    }
    trial_hashes = _current_trial_plan_hashes(conn)
    projected = []
    for row in conn.execute(
        "SELECT * FROM research_graph_branches ORDER BY created_at"
    ).fetchall():
        instance_id = str(row["instance_id"])
        branch_id = str(row["branch_id"])
        node_id = str(row["current_node"])
        resolution = resolutions.get(
            (instance_id, branch_id, node_id),
            instance_fallbacks.get(instance_id) or {"node_id": node_id},
        )
        _, serialized, resolution_hash = serialize_capability_resolution(
            resolution,
            node_id=node_id,
        )
        legacy_evidence_refs = orjson.loads(
            str(row["evidence_refs_json"] or "[]")
        )
        legacy_evidence_ref_count = (
            len(legacy_evidence_refs)
            if isinstance(legacy_evidence_refs, list)
            else 0
        )
        projected.append({
            "branch_id": branch_id,
            "hypothesis_branch_id": branch_id,
            "is_current_incarnation": 1,
            "instance_id": instance_id,
            "label": str(row["label"]),
            "current_node": node_id,
            "status": str(row["status"]),
            "current_capability_resolution_json": serialized,
            "current_capability_resolution_hash": resolution_hash,
            "current_trial_plan_hash": trial_hashes.get(
                (instance_id, branch_id),
                "",
            ),
            "evidence_refs_json": "[]",
            "omitted_evidence_count": int(
                row["omitted_evidence_count"] or 0
            ) + legacy_evidence_ref_count,
            "latest_trace_id": "",
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        })
    return projected


def _current_trial_plan_hashes(
    conn: sqlite3.Connection,
) -> dict[tuple[str, str], str]:
    values: dict[tuple[str, str], str] = {}
    rows = conn.execute(
        """
        SELECT instance_id, branch_id, evidence_json
        FROM research_graph_trace
        ORDER BY created_at, trace_id
        """
    ).fetchall()
    for row in rows:
        evidence = orjson.loads(row["evidence_json"]) or {}
        if "trial_plan_hash" not in evidence:
            continue
        values[
            (str(row["instance_id"]), str(row["branch_id"]))
        ] = validate_trial_plan_hash(evidence["trial_plan_hash"])
    return values


def _write_instances(
    conn: sqlite3.Connection,
    instances: list[dict[str, Any]],
) -> None:
    conn.executemany(
        """
        INSERT INTO research_graph_instances (
            instance_id, work_package_id, owner, graph_id, graph_version,
            product_group,
            workspace_id, mode, shadow_run_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            tuple(instance[key] for key in (
                "instance_id",
                "work_package_id",
                "owner",
                "graph_id",
                "graph_version",
                "product_group",
                "workspace_id",
                "mode",
                "shadow_run_id",
                "created_at",
            ))
            for instance in instances
        ],
    )


def _write_branches(
    conn: sqlite3.Connection,
    branches: list[dict[str, Any]],
) -> None:
    keys = (
        "branch_id",
        "hypothesis_branch_id",
        "is_current_incarnation",
        "instance_id",
        "label",
        "current_node",
        "status",
        "current_capability_resolution_json",
        "current_capability_resolution_hash",
        "current_trial_plan_hash",
        "evidence_refs_json",
        "omitted_evidence_count",
        "latest_trace_id",
        "created_at",
        "updated_at",
    )
    conn.executemany(
        """
        INSERT INTO research_graph_branches (
            branch_id, hypothesis_branch_id, is_current_incarnation,
            instance_id, label, current_node, status,
            current_capability_resolution_json,
            current_capability_resolution_hash, current_trial_plan_hash,
            evidence_refs_json, omitted_evidence_count, latest_trace_id,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [tuple(branch[key] for key in keys) for branch in branches],
    )


def _validate_target(
    conn: sqlite3.Connection,
    instances: list[dict[str, Any]],
    branches: list[dict[str, Any]],
) -> None:
    if _count_rows(conn, "research_graph_instances") != len(instances):
        raise ValueError("Graph instance migration count mismatch")
    if _count_rows(conn, "research_graph_branches") != len(branches):
        raise ValueError("Graph branch migration count mismatch")
    columns = table_columns(conn, "research_graph_branches")
    if _RESOURCE_COLUMNS.intersection(columns):
        raise ValueError("branch resource aggregates survived migration")


def _resource_totals(conn: sqlite3.Connection) -> dict[str, int]:
    columns = table_columns(conn, "research_graph_branches")
    available = sorted(_RESOURCE_COLUMNS.intersection(columns))
    if not available:
        return {}
    row = conn.execute(
        "SELECT " + ", ".join(
            f"COALESCE(SUM({column}), 0) AS {column}"
            for column in available
        ) + " FROM research_graph_branches"
    ).fetchone()
    return {column: int(row[column]) for column in available}


def _is_target_schema(
    conn: sqlite3.Connection,
    tables: set[str],
) -> bool:
    if {
        "research_graph_node_resolutions",
        "research_capability_receipts",
    }.intersection(tables):
        return False
    branch_columns = table_columns(conn, "research_graph_branches")
    return {
        "current_capability_resolution_json",
        "current_capability_resolution_hash",
        "current_trial_plan_hash",
    }.issubset(branch_columns)


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
    }


def _count_rows(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(
        f"SELECT COUNT(*) FROM {table}"
    ).fetchone()[0])


def _empty_report(started: float, table_count: int) -> dict[str, Any]:
    return {
        "instances_migrated": 0,
        "branches_migrated": 0,
        "node_resolution_rows_projected": 0,
        "capability_receipt_rows_dropped": 0,
        "resource_aggregate_totals_discarded": {},
        "schema_tables_before": table_count,
        "schema_tables_after": table_count,
        "schema_tables_removed": 0,
        "transactions": 0,
        "rollback_target": (
            "restore pre-migration database backup and parent commit 3045e844"
        ),
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
    }
