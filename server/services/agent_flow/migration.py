"""Atomic offline migration from legacy Graph accounting into Agent Flow."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from .legacy_migration_prepare import prepare_legacy_accounting
from .schema import connect_agent_flow
from .store import AgentFlowStore, _CHARGING_POLICY_VERSION


_LEGACY_ACCOUNTING_TABLES = (
    "research_agent_executions",
    "research_token_budgets",
    "research_token_reservations",
    "research_provider_usage_receipts",
)


def migrate_legacy_graph_accounting(
    *,
    graph_db_path: str | Path,
    store: AgentFlowStore,
    agent_id_by_scope: dict[tuple[str, str], str],
) -> dict[str, int]:
    """Move all legacy accounting owners in one cross-database transaction."""
    graph_path = Path(graph_db_path).expanduser().resolve()
    target_path = Path(store.db_path).expanduser().resolve()
    if graph_path == target_path:
        raise ValueError("legacy Graph and Agent Flow databases must differ")

    conn = connect_agent_flow(target_path)
    attached = False
    try:
        conn.execute("ATTACH DATABASE ? AS legacy_graph", (str(graph_path),))
        attached = True
        # Super-journal atomicity across attached files requires rollback
        # journals. This command is intentionally an offline cutover.
        conn.execute("PRAGMA main.journal_mode=DELETE")
        conn.execute("PRAGMA legacy_graph.journal_mode=DELETE")
        existing_tables = {
            str(row["name"])
            for row in conn.execute(
                """
                SELECT name FROM legacy_graph.sqlite_master
                WHERE type='table'
                """
            )
        }
        present = set(_LEGACY_ACCOUNTING_TABLES).intersection(existing_tables)
        if not present:
            return _empty_report()
        missing = set(_LEGACY_ACCOUNTING_TABLES) - existing_tables
        if missing:
            raise ValueError(
                "legacy accounting schema is incomplete: "
                + ", ".join(sorted(missing))
            )

        conn.execute("BEGIN IMMEDIATE")
        migration = prepare_legacy_accounting(
            budgets=conn.execute(
                "SELECT * FROM legacy_graph.research_token_budgets"
            ).fetchall(),
            reservations=conn.execute(
                "SELECT * FROM legacy_graph.research_token_reservations"
            ).fetchall(),
            receipts=conn.execute(
                "SELECT * FROM legacy_graph.research_provider_usage_receipts"
            ).fetchall(),
            executions=conn.execute(
                "SELECT * FROM legacy_graph.research_agent_executions"
            ).fetchall(),
            agent_id_by_scope=agent_id_by_scope,
        )
        _assert_target_has_no_collisions(conn, migration)
        _insert_periods(conn, migration["periods"])
        _insert_invocations(conn, migration["invocations"])
        _validate_target_aggregates(conn, migration["periods"])
        for table in _LEGACY_ACCOUNTING_TABLES:
            conn.execute(f"DROP TABLE legacy_graph.{table}")
        conn.commit()
        return {
            "budget_periods_migrated": len(migration["periods"]),
            "invocations_migrated": len(migration["invocations"]),
            "legacy_tables_dropped": len(_LEGACY_ACCOUNTING_TABLES),
        }
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        if attached:
            try:
                conn.execute("DETACH DATABASE legacy_graph")
            except sqlite3.Error:
                pass
        conn.close()


def _empty_report() -> dict[str, int]:
    return {
        "budget_periods_migrated": 0,
        "invocations_migrated": 0,
        "legacy_tables_dropped": 0,
    }


def _assert_target_has_no_collisions(
    conn: sqlite3.Connection,
    migration: dict[str, list[dict[str, Any]]],
) -> None:
    for period in migration["periods"]:
        existing = conn.execute(
            """
            SELECT period_id, reset_pending FROM agent_budget_periods
            WHERE period_id=? OR (
                owner_user_id=? AND agent_id=? AND status='open'
            )
            """,
            (
                period["period_id"],
                period["owner_user_id"],
                period["agent_id"],
            ),
        ).fetchone()
        if existing is not None:
            detail = (
                " with pending reset"
                if bool(existing["reset_pending"]) else ""
            )
            raise ValueError(
                "Agent budget period collision" + detail + ": "
                + str(existing["period_id"])
            )
    for invocation in migration["invocations"]:
        existing = conn.execute(
            """
            SELECT invocation_id FROM agent_invocations
            WHERE invocation_id=? OR legacy_reservation_id=?
               OR (
                    owner_user_id=? AND provider_request_hash<>''
                    AND provider_request_hash=?
               )
            """,
            (
                invocation["invocation_id"],
                invocation["legacy_reservation_id"],
                invocation["owner_user_id"],
                invocation["provider_request_hash"],
            ),
        ).fetchone()
        if existing is not None:
            raise ValueError(
                "Agent invocation collision: "
                + str(existing["invocation_id"])
            )


def _insert_periods(
    conn: sqlite3.Connection,
    periods: list[dict[str, Any]],
) -> None:
    conn.executemany(
        """
        INSERT INTO agent_budget_periods (
            period_id, owner_user_id, agent_id, token_limit, used_tokens,
            reserved_tokens, charging_policy_version, revision, status,
            reset_pending, created_at
        ) VALUES (
            :period_id, :owner_user_id, :agent_id, :token_limit, :used_tokens,
            :reserved_tokens, :charging_policy_version, 1, 'open', 0,
            :created_at
        )
        """,
        [
            period | {
                "charging_policy_version": _CHARGING_POLICY_VERSION,
            }
            for period in periods
        ],
    )


def _insert_invocations(
    conn: sqlite3.Connection,
    invocations: list[dict[str, Any]],
) -> None:
    conn.executemany(
        """
        INSERT INTO agent_invocations (
            invocation_id, period_id, owner_user_id, agent_id,
            legacy_reservation_id, legacy_provider_receipt_id, actor_role,
            authority_scope, purpose, runtime_id, model_id, provider_id,
            agent_principal_hash, lineage_hash, launcher_attestation_hash,
            max_input_tokens, max_output_tokens, reserved_tokens,
            reservation_expires_at, input_tokens, output_tokens,
            cache_read_tokens, charged_tokens, measurement_quality,
            provider_request_hash, provider_attestation_hash, status,
            created_at, settled_at
        ) VALUES (
            :invocation_id, :period_id, :owner_user_id, :agent_id,
            :legacy_reservation_id, :legacy_provider_receipt_id, :actor_role,
            :authority_scope, :purpose, :runtime_id, :model_id, :provider_id,
            :agent_principal_hash, :lineage_hash,
            :launcher_attestation_hash, :max_input_tokens,
            :max_output_tokens, :reserved_tokens, :reservation_expires_at,
            :input_tokens, :output_tokens, 0, :charged_tokens,
            :measurement_quality, :provider_request_hash,
            :provider_attestation_hash, :status, :created_at, :settled_at
        )
        """,
        invocations,
    )


def _validate_target_aggregates(
    conn: sqlite3.Connection,
    periods: list[dict[str, Any]],
) -> None:
    for period in periods:
        row = conn.execute(
            """
            SELECT
                p.used_tokens,
                p.reserved_tokens,
                COALESCE(SUM(
                    CASE WHEN i.status='settled' THEN i.charged_tokens ELSE 0 END
                ), 0) AS invocation_used,
                COALESCE(SUM(
                    CASE WHEN i.status='reserved' THEN i.reserved_tokens ELSE 0 END
                ), 0) AS invocation_reserved
            FROM agent_budget_periods p
            LEFT JOIN agent_invocations i
              ON i.period_id=p.period_id
             AND i.owner_user_id=p.owner_user_id
             AND i.agent_id=p.agent_id
            WHERE p.period_id=?
            GROUP BY p.period_id
            """,
            (period["period_id"],),
        ).fetchone()
        if row is None or (
            int(row["used_tokens"]) != int(row["invocation_used"])
            or int(row["reserved_tokens"])
            != int(row["invocation_reserved"])
        ):
            raise ValueError(
                "migrated Agent Flow accounting aggregate mismatch"
            )
