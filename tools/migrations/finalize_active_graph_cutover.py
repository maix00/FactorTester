"""Offline coordinator for the Active Graph schema cutover.

The cutover owns Graph persistence only.  Agent token budgets, reservations,
provider usage receipts, and their migration are intentionally absent: token
accounting is not a FactorTester feature.  Execution identity is kept in the
separate ``agent_execution`` store and is not part of this migration.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any

from server.services.backend_assurance_migration import migrate_backend_assurance
from server.services.research_graph.branch.migration import (
    migrate_graph_branch_projection,
)
from server.services.research_graph.schema import (
    create_schema as create_graph_schema,
    final_schema_report,
)
from tools.data.sqlite.db import connect_sqlite


_LEGACY_TOKEN_TABLES = frozenset({
    "research_token_budgets",
    "research_token_reservations",
    "research_provider_usage_receipts",
})
_LEGACY_GRAPH_CONTROL_TABLES = frozenset({
    "research_agent_executions",
    "research_graph_validations",
    "research_graph_proposals",
    "research_graph_reviews",
    "research_graph_audits",
    "human_activation_authorizations",
    "research_capability_approvals",
    "research_graph_server_secrets",
    "research_graph_node_resolutions",
    "research_capability_receipts",
    "research_graph_rollbacks",
})
_LEGACY_TABLES = _LEGACY_TOKEN_TABLES | _LEGACY_GRAPH_CONTROL_TABLES


def inspect_cutover(*, graph_db_path: str | Path) -> dict[str, Any]:
    """Return a read-only plan for the remaining Graph migrations."""
    graph_path = Path(graph_db_path).expanduser().resolve()
    graph_tables = _tables(graph_path)
    return {
        "graph_db": str(graph_path),
        "graph_tables_before": sorted(graph_tables),
        "legacy_token_tables": sorted(graph_tables & _LEGACY_TOKEN_TABLES),
        "legacy_graph_control_tables": sorted(
            graph_tables & _LEGACY_GRAPH_CONTROL_TABLES
        ),
        "planned_batches": [
            name
            for name, required in (
                (
                    "backend_assurance",
                    _needs_backend_assurance_cutover(
                        graph_path,
                        graph_tables,
                    ),
                ),
                (
                    "branch_projection",
                    _needs_branch_cutover(graph_path, graph_tables),
                ),
                (
                    "remove_legacy_graph_control",
                    bool(graph_tables & _LEGACY_TABLES),
                ),
            )
            if required
        ],
    }


def finalize_cutover(
    *,
    graph_db_path: str | Path,
    backup_dir: str | Path,
) -> dict[str, Any]:
    """Apply Graph migrations atomically with a single recoverable backup."""
    started = time.perf_counter()
    graph_path = Path(graph_db_path).expanduser().resolve()
    if not graph_path.exists():
        raise FileNotFoundError(f"Graph database not found: {graph_path}")
    backup_root = Path(backup_dir).expanduser().resolve()
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    graph_backup = backup_root / f"graph-{graph_path.name}.{stamp}.bak"
    _backup_database(graph_path, graph_backup)

    reports: dict[str, Any] = {}
    try:
        before = inspect_cutover(graph_db_path=graph_path)
        if _needs_backend_assurance_cutover(graph_path, _tables(graph_path)):
            reports["backend_assurance"] = migrate_backend_assurance(
                graph_path,
            )
        if _needs_branch_cutover(graph_path, _tables(graph_path)):
            reports["branch_projection"] = migrate_graph_branch_projection(
                db_path=graph_path,
            )
        legacy_tables = _tables(graph_path) & _LEGACY_TABLES
        if legacy_tables:
            reports["remove_legacy_graph_control"] = _remove_legacy_tables(
                graph_path,
                legacy_tables,
            )
        with connect_sqlite(graph_path) as conn:
            create_graph_schema(conn)
            graph_report = final_schema_report(conn)
        if not graph_report["is_final"]:
            raise RuntimeError(f"final Graph schema check failed: {graph_report}")
        remaining_legacy_tables = _tables(graph_path) & _LEGACY_TABLES
        if remaining_legacy_tables:
            raise RuntimeError(
                "legacy Graph control tables survived cutover: "
                + ", ".join(sorted(remaining_legacy_tables))
            )
    except Exception:
        _restore_database(graph_backup, graph_path)
        raise
    return {
        "success": True,
        "migration_order": [
            "backend_assurance",
            "branch_projection",
            "remove_legacy_graph_control",
        ],
        "batch_reports": reports,
        "graph_schema": graph_report,
        "graph_backup": str(graph_backup),
        "rollback_target": (
            "restore the listed Graph backup and parent Graph migration commit"
        ),
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def _tables(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with connect_sqlite(path) as conn:
        return {
            str(row["name"])
            for row in conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
        }


def _remove_legacy_tables(
    path: Path,
    tables: set[str],
) -> dict[str, Any]:
    """Remove obsolete token and Graph-control tables after projection."""
    removed = sorted(tables & _LEGACY_TABLES)
    if not removed:
        return {"tables_removed": []}
    with connect_sqlite(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for table in removed:
                conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"tables_removed": removed}


def _needs_branch_cutover(path: Path, tables: set[str]) -> bool:
    if "research_graph_instances" not in tables:
        return False
    if {
        "research_graph_node_resolutions",
        "research_capability_receipts",
    } & tables:
        return True
    with connect_sqlite(path) as conn:
        columns = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(research_graph_branches)"
            ).fetchall()
        }
    return "current_capability_resolution_json" not in columns


def _needs_backend_assurance_cutover(
    path: Path,
    tables: set[str],
) -> bool:
    if "research_backend_assurance_receipts" in tables:
        return True
    if "research_jobs" not in tables:
        return False
    with connect_sqlite(path) as conn:
        columns = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(research_jobs)"
            ).fetchall()
        }
        if "status" not in columns:
            return False
        assurance_predicate = (
            "terminal_assurance_json IS NULL"
            if "terminal_assurance_json" in columns
            else "1=1"
        )
        row = conn.execute(
            f"""
            SELECT 1 FROM research_jobs
            WHERE status IN ('succeeded', 'failed', 'cancelled')
            LIMIT 1
            """
        ).fetchone()
    return row is not None


def _backup_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with connect_sqlite(source) as src, connect_sqlite(target) as dst:
        src.backup(dst)


def _restore_database(source: Path, target: Path) -> None:
    with connect_sqlite(source) as src, connect_sqlite(target) as dst:
        src.backup(dst)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph-db", required=True, type=Path)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-offline", action="store_true")
    args = parser.parse_args()
    try:
        if not args.apply:
            report = inspect_cutover(graph_db_path=args.graph_db)
            report["success"] = True
            report["mode"] = "dry_run"
        else:
            if not args.confirm_offline:
                raise ValueError("--apply requires --confirm-offline")
            report = finalize_cutover(
                graph_db_path=args.graph_db,
                backup_dir=args.backup_dir or args.graph_db.parent,
            )
            report["mode"] = "applied"
    except Exception as exc:
        report = {
            "success": False,
            "error": str(exc),
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
