"""Atomic offline migration from legacy Graph accounting into Agent Flow."""

from __future__ import annotations

from collections import defaultdict
import hashlib
from pathlib import Path
import sqlite3
from typing import Any

from .schema import connect_agent_flow
from .store import AgentFlowStore, _CHARGING_POLICY_VERSION


_LEGACY_ACCOUNTING_TABLES = (
    "research_agent_executions",
    "research_token_budgets",
    "research_token_reservations",
    "research_provider_usage_receipts",
)
_VALID_RESERVATION_STATUSES = {"granted", "committed", "released"}


def migrate_legacy_graph_accounting(
    *,
    graph_db_path: str | Path,
    store: AgentFlowStore,
    agent_id_by_scope: dict[tuple[str, str], str],
) -> dict[str, int]:
    """Move all legacy accounting owners in one cross-database transaction.

    ``agent_id_by_scope`` is deliberately explicit: a legacy budget scope is
    not necessarily an Agent identity and migration must not guess one.
    """
    graph_path = Path(graph_db_path).expanduser().resolve()
    target_path = Path(store.db_path).expanduser().resolve()
    if graph_path == target_path:
        raise ValueError("legacy Graph and Agent Flow databases must differ")

    conn = connect_agent_flow(target_path)
    attached = False
    try:
        conn.execute("ATTACH DATABASE ? AS legacy_graph", (str(graph_path),))
        attached = True
        # SQLite's super-journal provides atomic commit across attached files
        # only with rollback journals. This is an offline cutover, so refuse
        # to retain WAL mode for either participant.
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
        budgets = conn.execute(
            "SELECT * FROM legacy_graph.research_token_budgets"
        ).fetchall()
        reservations = conn.execute(
            "SELECT * FROM legacy_graph.research_token_reservations"
        ).fetchall()
        receipts = conn.execute(
            "SELECT * FROM legacy_graph.research_provider_usage_receipts"
        ).fetchall()
        executions = conn.execute(
            "SELECT * FROM legacy_graph.research_agent_executions"
        ).fetchall()

        migration = _validate_and_prepare(
            budgets=budgets,
            reservations=reservations,
            receipts=receipts,
            executions=executions,
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


def _validate_and_prepare(
    *,
    budgets: list[sqlite3.Row],
    reservations: list[sqlite3.Row],
    receipts: list[sqlite3.Row],
    executions: list[sqlite3.Row],
    agent_id_by_scope: dict[tuple[str, str], str],
) -> dict[str, list[dict[str, Any]]]:
    budget_by_scope: dict[tuple[str, str], sqlite3.Row] = {}
    for row in budgets:
        scope_key = (str(row["owner_user_id"]), str(row["scope_id"]))
        if scope_key in budget_by_scope:
            raise ValueError(
                f"duplicate legacy token budget: {scope_key[0]}:{scope_key[1]}"
            )
        budget_by_scope[scope_key] = row

    required_scope_keys = set(budget_by_scope)
    for row in reservations:
        required_scope_keys.add(
            (str(row["owner_user_id"]), str(row["scope_id"]))
        )
    missing_mappings = sorted(
        scope for scope in required_scope_keys
        if not str(agent_id_by_scope.get(scope) or "").strip()
    )
    if missing_mappings:
        owner, scope_id = missing_mappings[0]
        raise ValueError(
            "legacy Agent identity mapping is required for "
            f"{owner}:{scope_id}"
        )

    receipt_by_id = {
        str(row["provider_receipt_id"]): row for row in receipts
    }
    execution_by_reservation: dict[str, sqlite3.Row] = {}
    for row in executions:
        reservation_id = str(row["reservation_id"])
        if reservation_id in execution_by_reservation:
            raise ValueError(
                "multiple legacy Agent executions reference reservation "
                f"{reservation_id}"
            )
        execution_by_reservation[reservation_id] = row

    reservation_ids = {
        str(row["reservation_id"]) for row in reservations
    }
    orphan_execution_ids = (
        set(execution_by_reservation) - reservation_ids
    )
    if orphan_execution_ids:
        raise ValueError(
            "legacy Agent execution references unknown reservation "
            + sorted(orphan_execution_ids)[0]
        )

    referenced_receipts: set[str] = set()
    invocation_rows: list[dict[str, Any]] = []
    aggregate_used: defaultdict[tuple[str, str], int] = defaultdict(int)
    aggregate_reserved: defaultdict[tuple[str, str], int] = defaultdict(int)

    for reservation in reservations:
        owner = str(reservation["owner_user_id"])
        scope_id = str(reservation["scope_id"])
        scope_key = (owner, scope_id)
        budget = budget_by_scope.get(scope_key)
        if budget is None:
            raise ValueError(
                f"legacy reservation has no token budget: {owner}:{scope_id}"
            )
        reservation_id = str(reservation["reservation_id"])
        status = str(reservation["status"])
        if status not in _VALID_RESERVATION_STATUSES:
            raise ValueError(
                f"invalid legacy reservation status: {status}"
            )
        max_input = int(reservation["max_input_tokens"])
        max_output = int(reservation["max_output_tokens"])
        reserved_tokens = int(reservation["max_total_tokens"])
        if reserved_tokens <= 0 or reserved_tokens != max_input + max_output:
            raise ValueError(
                f"legacy reservation total is inconsistent: {reservation_id}"
            )

        receipt_id = str(reservation["provider_receipt_id"] or "")
        receipt = receipt_by_id.get(receipt_id) if receipt_id else None
        if receipt_id:
            if receipt is None:
                raise ValueError(
                    "legacy provider receipt is missing: " + receipt_id
                )
            if str(receipt["reservation_id"]) != reservation_id:
                raise ValueError(
                    "legacy provider receipt does not match reservation "
                    f"{reservation_id}"
                )
            referenced_receipts.add(receipt_id)
        dangling_for_reservation = [
            str(row["provider_receipt_id"])
            for row in receipts
            if str(row["reservation_id"]) == reservation_id
            and str(row["provider_receipt_id"]) != receipt_id
        ]
        if dangling_for_reservation:
            raise ValueError(
                "legacy reservation has an unreferenced provider receipt: "
                + dangling_for_reservation[0]
            )
        if receipt is not None and status != "committed":
            raise ValueError(
                "only a committed reservation may reference provider usage"
            )

        execution = execution_by_reservation.get(reservation_id)
        if execution is not None and str(
            execution["owner_user_id"]
        ) != owner:
            raise ValueError(
                "legacy Agent execution owner does not match reservation "
                f"{reservation_id}"
            )

        if status == "committed":
            invocation_status = "settled"
            if receipt is None:
                input_tokens = None
                output_tokens = None
                charged_tokens = reserved_tokens
                measurement_quality = "reserved_fallback"
            else:
                input_tokens = int(receipt["input_tokens"])
                output_tokens = int(receipt["output_tokens"])
                if input_tokens > max_input or output_tokens > max_output:
                    raise ValueError(
                        "legacy provider usage exceeds reservation "
                        f"{reservation_id}"
                    )
                charged_tokens = input_tokens + output_tokens
                measurement_quality = "provider_actual"
            aggregate_used[scope_key] += charged_tokens
        elif status == "granted":
            invocation_status = "reserved"
            input_tokens = output_tokens = charged_tokens = None
            measurement_quality = ""
            aggregate_reserved[scope_key] += reserved_tokens
        else:
            invocation_status = "released"
            input_tokens = output_tokens = charged_tokens = None
            measurement_quality = ""

        agent_id = str(agent_id_by_scope[scope_key]).strip()
        invocation_rows.append({
            "invocation_id": (
                str(execution["execution_id"])
                if execution is not None
                else reservation_id
            ),
            "period_id": _legacy_period_id(owner, scope_id),
            "owner_user_id": owner,
            "agent_id": agent_id,
            "legacy_reservation_id": reservation_id,
            "legacy_provider_receipt_id": receipt_id,
            "actor_role": (
                str(execution["actor_role"])
                if execution is not None
                else str(reservation["work_kind"])
            ),
            "authority_scope": (
                str(execution["authority_scope"])
                if execution is not None
                else "local_research"
            ),
            "purpose": str(reservation["work_kind"]),
            "runtime_id": (
                str(execution["codex_version"])
                if execution is not None
                else "legacy"
            ),
            "model_id": (
                str(execution["model_id"])
                if execution is not None
                else ""
            ),
            "provider_id": (
                str(receipt["provider"]) if receipt is not None else ""
            ),
            "agent_principal_hash": (
                str(execution["agent_principal_hash"])
                if execution is not None
                else _hash(f"{owner}:{reservation_id}")
            ),
            "lineage_hash": (
                str(execution["lineage_hash"])
                if execution is not None
                else _hash(f"legacy:{owner}:{reservation_id}")
            ),
            "launcher_attestation_hash": (
                _hash(str(execution["launcher_attestation"]))
                if execution is not None else ""
            ),
            "max_input_tokens": max_input,
            "max_output_tokens": max_output,
            "reserved_tokens": reserved_tokens,
            "reservation_expires_at": float(reservation["expires_at"]),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "charged_tokens": charged_tokens,
            "measurement_quality": measurement_quality,
            "provider_request_hash": (
                _hash(str(receipt["provider_request_id"]))
                if receipt is not None else ""
            ),
            "provider_attestation_hash": (
                _hash(str(receipt["usage_attestation"]))
                if receipt is not None else ""
            ),
            "status": invocation_status,
            "created_at": float(reservation["created_at"]),
            "settled_at": (
                None if invocation_status == "reserved"
                else float(
                    receipt["created_at"]
                    if receipt is not None
                    else (
                        execution["created_at"]
                        if execution is not None
                        else reservation["created_at"]
                    )
                )
            ),
        })

    orphan_receipts = set(receipt_by_id) - referenced_receipts
    if orphan_receipts:
        raise ValueError(
            "legacy provider receipt is not referenced by its reservation: "
            + sorted(orphan_receipts)[0]
        )

    period_rows: list[dict[str, Any]] = []
    for scope_key, budget in budget_by_scope.items():
        owner, scope_id = scope_key
        expected_used = aggregate_used[scope_key]
        expected_reserved = aggregate_reserved[scope_key]
        if int(budget["used_tokens"]) != expected_used or int(
            budget["reserved_tokens"]
        ) != expected_reserved:
            raise ValueError(
                "legacy token budget aggregate mismatch for "
                f"{owner}:{scope_id}: expected used/reserved "
                f"{expected_used}/{expected_reserved}"
            )
        period_rows.append({
            "period_id": _legacy_period_id(owner, scope_id),
            "owner_user_id": owner,
            "agent_id": str(agent_id_by_scope[scope_key]).strip(),
            "token_limit": int(budget["token_limit"]),
            "used_tokens": expected_used,
            "reserved_tokens": expected_reserved,
            "created_at": float(budget["created_at"]),
        })

    return {"periods": period_rows, "invocations": invocation_rows}


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


def _legacy_period_id(owner_user_id: str, scope_id: str) -> str:
    return "legacy-" + _hash(f"{owner_user_id}\0{scope_id}")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
