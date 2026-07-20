"""Offline coordinator for the six-batch Active Graph cutover."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time
from typing import Any

from server.services.agent_flow import (
    AgentFlowStore,
    finalize_agent_flow_schema,
    migrate_legacy_graph_accounting,
)
from server.services.agent_flow.schema import (
    AGENT_INVOCATION_COLUMNS,
    table_columns as agent_flow_table_columns,
)
from server.services.backend_assurance_migration import (
    migrate_backend_assurance,
)
from server.services.graph_governance_migration import (
    migrate_graph_governance,
)
from server.services.research_graph.activation_migration import (
    migrate_graph_activation_pointer,
)
from server.services.research_graph.branch.migration import (
    migrate_graph_branch_projection,
)
from server.services.research_graph.schema import (
    create_schema as create_graph_schema,
    final_schema_report,
)
from tools.data.sqlite.db import connect_sqlite


_ACCOUNTING_TABLES = frozenset({
    "research_agent_executions",
    "research_token_budgets",
    "research_token_reservations",
    "research_provider_usage_receipts",
})
_GOVERNANCE_TABLES = frozenset({
    "research_graph_validations",
    "research_graph_proposals",
    "research_graph_reviews",
    "research_graph_audits",
    "human_activation_authorizations",
    "research_capability_approvals",
    "research_graph_server_secrets",
})


def inspect_cutover(
    *,
    graph_db_path: str | Path,
    agent_flow_db_path: str | Path,
) -> dict[str, Any]:
    graph_path = Path(graph_db_path).expanduser().resolve()
    flow_path = Path(agent_flow_db_path).expanduser().resolve()
    graph_tables = _tables(graph_path)
    flow_tables = _tables(flow_path)
    return {
        "graph_db": str(graph_path),
        "agent_flow_db": str(flow_path),
        "graph_tables_before": sorted(graph_tables),
        "agent_flow_tables_before": sorted(flow_tables),
        "required_agent_scope_mappings": _legacy_agent_scopes(
            graph_path,
            graph_tables,
        ),
        "required_rollback_owner_mappings": _legacy_rollback_actors(
            graph_path,
            graph_tables,
        ),
        "planned_batches": [
            name
            for name, required in (
                ("agent_flow", bool(graph_tables & _ACCOUNTING_TABLES)),
                (
                    "backend_assurance",
                    _needs_backend_assurance_cutover(
                        graph_path,
                        graph_tables,
                    ),
                ),
                (
                    "graph_governance",
                    bool(graph_tables & _GOVERNANCE_TABLES),
                ),
                (
                    "branch_projection",
                    _needs_branch_cutover(graph_path, graph_tables),
                ),
                (
                    "activation_pointer",
                    "research_graph_rollbacks" in graph_tables,
                ),
            )
            if required
        ],
    }


def finalize_cutover(
    *,
    graph_db_path: str | Path,
    agent_flow_db_path: str | Path,
    backup_dir: str | Path,
    agent_id_by_scope: dict[tuple[str, str], str],
    rollback_owner_by_actor: dict[str, str],
) -> dict[str, Any]:
    started = time.perf_counter()
    graph_path = Path(graph_db_path).expanduser().resolve()
    flow_path = Path(agent_flow_db_path).expanduser().resolve()
    if graph_path == flow_path:
        raise ValueError("Graph and Agent Flow databases must be separate")
    if not graph_path.exists():
        raise FileNotFoundError(f"Graph database not found: {graph_path}")
    backup_root = Path(backup_dir).expanduser().resolve()
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    flow_existed = flow_path.exists()
    graph_backup = backup_root / f"graph-{graph_path.name}.{stamp}.bak"
    flow_backup = backup_root / f"agent-flow-{flow_path.name}.{stamp}.bak"
    _backup_database(graph_path, graph_backup)
    if flow_existed:
        _backup_database(flow_path, flow_backup)

    reports: dict[str, Any] = {}
    try:
        before = inspect_cutover(
            graph_db_path=graph_path,
            agent_flow_db_path=flow_path,
        )
        graph_tables = set(before["graph_tables_before"])
        flow_tables_before = set(before["agent_flow_tables_before"])
        if flow_tables_before and flow_tables_before != {
            "agent_budget_periods",
            "agent_invocations",
        }:
            raise RuntimeError(
                "final Agent Flow schema has unexpected owners: "
                + ", ".join(sorted(flow_tables_before))
            )
        flow_schema_report = finalize_agent_flow_schema(
            db_path=flow_path,
        )
        if (
            flow_schema_report["schema_created"]
            or flow_schema_report["schema_rebuilt"]
        ):
            reports["agent_flow_schema"] = flow_schema_report
        flow_tables_after_schema = _tables(flow_path)
        if flow_tables_after_schema != {
            "agent_budget_periods",
            "agent_invocations",
        }:
            raise RuntimeError(
                "final Agent Flow schema has unexpected owners: "
                + ", ".join(sorted(flow_tables_after_schema))
            )
        store = AgentFlowStore(flow_path)
        if graph_tables & _ACCOUNTING_TABLES:
            reports["agent_flow"] = migrate_legacy_graph_accounting(
                graph_db_path=graph_path,
                store=store,
                agent_id_by_scope=agent_id_by_scope,
            )
        if _needs_backend_assurance_cutover(graph_path, graph_tables):
            reports["backend_assurance"] = migrate_backend_assurance(
                graph_path,
            )
        if graph_tables & _GOVERNANCE_TABLES:
            reports["graph_governance"] = migrate_graph_governance(
                db_path=graph_path,
            )
        if _needs_branch_cutover(graph_path, _tables(graph_path)):
            reports["branch_projection"] = migrate_graph_branch_projection(
                db_path=graph_path,
            )
        if "research_graph_rollbacks" in _tables(graph_path):
            reports["activation_pointer"] = (
                migrate_graph_activation_pointer(
                    db_path=graph_path,
                    actor_owner_mapping=rollback_owner_by_actor,
                )
            )
        with connect_sqlite(graph_path) as conn:
            create_graph_schema(conn)
            graph_report = final_schema_report(conn)
        flow_tables = _tables(flow_path)
        if not graph_report["is_final"]:
            raise RuntimeError(f"final Graph schema check failed: {graph_report}")
        if flow_tables != {"agent_budget_periods", "agent_invocations"}:
            raise RuntimeError(
                "final Agent Flow schema has unexpected owners: "
                + ", ".join(sorted(flow_tables))
            )
        with connect_sqlite(flow_path) as conn:
            invocation_columns = agent_flow_table_columns(
                conn,
                "agent_invocations",
            )
        if invocation_columns != AGENT_INVOCATION_COLUMNS:
            raise RuntimeError(
                "final Agent Flow invocation columns do not match contract"
            )
    except Exception:
        _restore_database(graph_backup, graph_path)
        if flow_existed:
            _restore_database(flow_backup, flow_path)
        elif flow_path.exists():
            flow_path.unlink()
        raise
    return {
        "success": True,
        "migration_order": [
            "agent_flow_schema",
            "agent_flow",
            "backend_assurance",
            "graph_governance",
            "branch_projection",
            "activation_pointer",
        ],
        "batch_reports": reports,
        "graph_schema": graph_report,
        "agent_flow_owner_tables": sorted(flow_tables),
        "graph_backup": str(graph_backup),
        "agent_flow_backup": str(flow_backup) if flow_existed else "",
        "rollback_target": (
            "restore both listed backups and parent commit 2d951a42"
            if flow_existed
            else (
                "restore the Graph backup, delete the newly created "
                "Agent Flow database, and restore parent commit 2d951a42"
            )
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


def _legacy_agent_scopes(
    path: Path,
    tables: set[str],
) -> list[dict[str, str]]:
    if "research_token_budgets" not in tables:
        return []
    with connect_sqlite(path) as conn:
        rows = conn.execute(
            """
            SELECT owner_user_id, scope_id FROM research_token_budgets
            ORDER BY owner_user_id, scope_id
            """
        ).fetchall()
    return [
        {
            "owner_user_id": str(row["owner_user_id"]),
            "scope_id": str(row["scope_id"]),
        }
        for row in rows
    ]


def _legacy_rollback_actors(
    path: Path,
    tables: set[str],
) -> list[str]:
    if "research_graph_rollbacks" not in tables:
        return []
    with connect_sqlite(path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT actor FROM research_graph_rollbacks ORDER BY actor"
        ).fetchall()
    return [str(row["actor"]) for row in rows]


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
              AND {assurance_predicate}
            LIMIT 1
            """
        ).fetchone()
    return row is not None


def _backup_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)


def _restore_database(source: Path, target: Path) -> None:
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)


def _agent_mapping(path: Path | None) -> dict[tuple[str, str], str]:
    if path is None:
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("agent mapping must be a JSON array")
    result = {}
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("agent mapping items must be objects")
        key = (
            str(item.get("owner_user_id") or ""),
            str(item.get("scope_id") or ""),
        )
        agent_id = str(item.get("agent_id") or "")
        if not all((*key, agent_id)):
            raise ValueError("agent mapping item is incomplete")
        result[key] = agent_id
    return result


def _rollback_mapping(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(owner, str) and key and owner
        for key, owner in value.items()
    ):
        raise ValueError("rollback owner mapping must be a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph-db", required=True, type=Path)
    parser.add_argument("--agent-flow-db", required=True, type=Path)
    parser.add_argument("--agent-map", type=Path)
    parser.add_argument("--rollback-owner-map", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-offline", action="store_true")
    args = parser.parse_args()
    try:
        if not args.apply:
            report = inspect_cutover(
                graph_db_path=args.graph_db,
                agent_flow_db_path=args.agent_flow_db,
            )
            report["success"] = True
            report["mode"] = "dry_run"
        else:
            if not args.confirm_offline:
                raise ValueError("--apply requires --confirm-offline")
            report = finalize_cutover(
                graph_db_path=args.graph_db,
                agent_flow_db_path=args.agent_flow_db,
                backup_dir=args.backup_dir or args.graph_db.parent,
                agent_id_by_scope=_agent_mapping(args.agent_map),
                rollback_owner_by_actor=_rollback_mapping(
                    args.rollback_owner_map
                ),
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
