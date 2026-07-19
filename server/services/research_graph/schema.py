"""Final six-owner Graph schema and startup cutover guard."""

from __future__ import annotations

import sqlite3

import settings as Settings
from server.services import agent_flow
from server.services.maintenance_cases.schema import (
    create_schema as create_maintenance_schema,
)
from server.services.research_graph.branch.schema import (
    create_instance_branch_schema,
    ensure_instance_branch_schema,
)
from server.services.research_graph.versions import (
    clear_graph_cache_for_current_db,
)
from tools.data.sqlite.db import connect_sqlite


GRAPH_OWNER_TABLES = frozenset({
    "research_graph_versions",
    "active_research_graphs",
    "research_graph_instances",
    "research_graph_branches",
    "research_graph_trace",
    "research_maintenance_cases",
})

LEGACY_GRAPH_TABLES = frozenset({
    "research_agent_executions",
    "research_token_budgets",
    "research_token_reservations",
    "research_provider_usage_receipts",
    "research_backend_assurance_receipts",
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


def ensure_schema() -> None:
    """Create a fresh target schema or reject an uncut legacy database."""
    clear_graph_cache_for_current_db()
    agent_flow.get_store().ensure_schema()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        definitions = _table_definitions(conn)
        tables = set(definitions)
        legacy = sorted(tables & LEGACY_GRAPH_TABLES)
        if legacy:
            raise RuntimeError(
                "legacy Graph schema requires explicit offline cutover "
                "(migrate_legacy_agent_flow, migrate_backend_assurance, "
                "migrate_graph_governance, "
                "migrate_graph_branch_projection, "
                "migrate_graph_activation_pointer): "
                + ", ".join(legacy)
            )
        if not GRAPH_OWNER_TABLES.issubset(tables):
            create_schema(conn)
            definitions = _table_definitions(conn)
            tables = set(definitions)
        if "trial_stage_projection_json" not in definitions.get(
            "research_graph_branches",
            "",
        ):
            ensure_instance_branch_schema(conn)
        missing = sorted(GRAPH_OWNER_TABLES - tables)
        if missing:
            raise RuntimeError(
                "final Graph schema is incomplete: " + ", ".join(missing)
            )


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS research_graph_versions (
            graph_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            lifecycle TEXT NOT NULL,
            parent_version INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            graph_json TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (graph_id, version),
            UNIQUE (graph_id, content_hash)
        );
        CREATE TABLE IF NOT EXISTS active_research_graphs (
            graph_id TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            activated_by TEXT NOT NULL,
            activated_at REAL NOT NULL
        );
        """
    )
    create_instance_branch_schema(conn)
    create_maintenance_schema(conn)


def final_schema_report(conn: sqlite3.Connection) -> dict[str, object]:
    tables = _table_names(conn)
    return {
        "graph_owner_tables": sorted(tables & GRAPH_OWNER_TABLES),
        "legacy_graph_tables": sorted(tables & LEGACY_GRAPH_TABLES),
        "owner_count": len(tables & GRAPH_OWNER_TABLES),
        "is_final": (
            GRAPH_OWNER_TABLES.issubset(tables)
            and not tables.intersection(LEGACY_GRAPH_TABLES)
        ),
    }


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return set(_table_definitions(conn))


def _table_definitions(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        str(row["name"]): str(row["sql"] or "")
        for row in conn.execute(
            """
            SELECT name, sql FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
    }
