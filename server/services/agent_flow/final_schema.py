"""Offline, atomic cutover from legacy Agent Invocation columns."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .schema import (
    AGENT_BUDGET_PERIOD_COLUMNS,
    AGENT_FLOW_OWNER_TABLES,
    AGENT_INVOCATION_COLUMNS,
    LEGACY_INVOCATION_COLUMNS,
    connect_agent_flow,
    create_schema,
    table_columns,
)


_INVOCATION_INDEXES = (
    "idx_agent_invocations_owner",
    "uq_agent_invocation_request",
    "uq_agent_provider_request",
    "uq_agent_legacy_reservation",
)


def finalize_agent_flow_schema(
    *,
    db_path: str | Path,
    failure_injector: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Drop legacy source IDs while preserving canonical invocation facts."""
    with connect_agent_flow(db_path) as conn:
        tables = _owner_tables(conn)
        if not tables:
            conn.execute("BEGIN IMMEDIATE")
            try:
                create_schema(conn)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            return _report(created=1, migrated=0, rows=0)
        if tables != AGENT_FLOW_OWNER_TABLES:
            raise ValueError(
                "Agent Flow owner schema is incomplete: "
                + ", ".join(sorted(tables))
            )
        budget_columns = table_columns(conn, "agent_budget_periods")
        if budget_columns != AGENT_BUDGET_PERIOD_COLUMNS:
            raise ValueError("Agent Budget Period columns are non-final")
        invocation_columns = table_columns(conn, "agent_invocations")
        legacy_columns = LEGACY_INVOCATION_COLUMNS.intersection(
            invocation_columns
        )
        if not legacy_columns:
            if invocation_columns != AGENT_INVOCATION_COLUMNS:
                raise ValueError("Agent Invocation columns are non-final")
            return _report(
                created=0,
                migrated=0,
                rows=_count_rows(conn, "agent_invocations"),
            )
        if (
            invocation_columns - LEGACY_INVOCATION_COLUMNS
            != AGENT_INVOCATION_COLUMNS
        ):
            raise ValueError(
                "legacy Agent Invocation has unsupported column drift"
            )
        row_count = _count_rows(conn, "agent_invocations")
        conn.execute("BEGIN IMMEDIATE")
        try:
            for index in _INVOCATION_INDEXES:
                conn.execute(f"DROP INDEX IF EXISTS {index}")
            conn.execute(
                "ALTER TABLE agent_invocations "
                "RENAME TO legacy_agent_invocations"
            )
            create_schema(conn)
            canonical_columns = sorted(AGENT_INVOCATION_COLUMNS)
            column_sql = ", ".join(canonical_columns)
            conn.execute(
                f"""
                INSERT INTO agent_invocations ({column_sql})
                SELECT {column_sql} FROM legacy_agent_invocations
                """
            )
            if failure_injector is not None:
                failure_injector("after_canonical_copy")
            if _count_rows(conn, "agent_invocations") != row_count:
                raise ValueError("Agent Invocation row count mismatch")
            conn.execute("DROP TABLE legacy_agent_invocations")
            if failure_injector is not None:
                failure_injector("after_legacy_drop")
            if table_columns(
                conn,
                "agent_invocations",
            ) != AGENT_INVOCATION_COLUMNS:
                raise ValueError("Agent Invocation final columns mismatch")
            foreign_key_errors = conn.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            if foreign_key_errors:
                raise ValueError("Agent Flow foreign key check failed")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return _report(created=0, migrated=1, rows=row_count)


def _owner_tables(conn) -> frozenset[str]:
    return frozenset(
        str(row["name"])
        for row in conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
    )


def _count_rows(conn, table: str) -> int:
    return int(conn.execute(
        f"SELECT COUNT(*) FROM {table}"
    ).fetchone()[0])


def _report(
    *,
    created: int,
    migrated: int,
    rows: int,
) -> dict[str, Any]:
    return {
        "schema_created": bool(created),
        "schema_rebuilt": bool(migrated),
        "invocations_preserved": rows,
        "legacy_columns_removed": (
            sorted(LEGACY_INVOCATION_COLUMNS) if migrated else []
        ),
        "owner_tables": sorted(AGENT_FLOW_OWNER_TABLES),
        "invocation_columns": sorted(AGENT_INVOCATION_COLUMNS),
    }
