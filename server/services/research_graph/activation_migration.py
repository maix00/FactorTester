"""Explicit Batch 5 migration to pointer-only Graph activation history."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
from pathlib import Path
import time
from typing import Any

import orjson

from server.services.maintenance_cases.schema import (
    create_schema as create_maintenance_schema,
)
from tools.data.sqlite.db import connect_sqlite


_ROLLBACK_TABLE = "research_graph_rollbacks"


def migrate_graph_activation_pointer(
    *,
    db_path: str | Path,
    actor_owner_mapping: Mapping[str, str] | None = None,
    failure_injector: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Convert legacy rollback rows to bounded history and drop their table."""
    started = time.perf_counter()
    with connect_sqlite(Path(db_path)) as conn:
        tables = _table_names(conn)
        if _ROLLBACK_TABLE not in tables:
            return _empty_report(started, len(tables))
        before_count = len(tables)
        _validate_pointer_targets(conn)
        rollback_rows = conn.execute(
            f"SELECT * FROM {_ROLLBACK_TABLE} ORDER BY created_at, rollback_id"
        ).fetchall()
        owners = _resolve_owners(
            rollback_rows,
            actor_owner_mapping or {},
        )
        conn.execute("BEGIN IMMEDIATE")
        try:
            create_maintenance_schema(conn)
            inserted = _write_historical_cases(
                conn,
                rollback_rows,
                owners,
            )
            if failure_injector is not None:
                failure_injector("after_history_projection")
            conn.execute(f"DROP TABLE {_ROLLBACK_TABLE}")
            if failure_injector is not None:
                failure_injector("after_legacy_drop")
            _validate_pointer_targets(conn)
            after_count = len(_table_names(conn))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {
        "active_pointers_validated": _active_pointer_count(db_path),
        "legacy_rollback_rows_projected": len(rollback_rows),
        "historical_cases_inserted": inserted,
        "schema_tables_before": before_count,
        "schema_tables_after": after_count,
        "schema_tables_removed": before_count - after_count,
        "transactions": 1,
        "rollback_target": (
            "restore pre-migration database backup and parent commit 2f793cc2"
        ),
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def has_legacy_rollback_table(conn: Any) -> bool:
    return conn.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type='table' AND name=?
        """,
        (_ROLLBACK_TABLE,),
    ).fetchone() is not None


def _resolve_owners(
    rows: list[Any],
    mapping: Mapping[str, str],
) -> dict[str, str]:
    owners: dict[str, str] = {}
    missing = []
    for row in rows:
        actor = str(row["actor"])
        owner = str(mapping.get(actor) or "").strip()
        if not owner:
            missing.append(actor)
        owners[actor] = owner
    if missing:
        raise ValueError(
            "legacy rollback actor requires explicit owner mapping: "
            + ", ".join(sorted(set(missing)))
        )
    return owners


def _write_historical_cases(
    conn: Any,
    rows: list[Any],
    owners: Mapping[str, str],
) -> int:
    inserted = 0
    for row in rows:
        actor = str(row["actor"])
        reason_hash = hashlib.sha256(
            str(row["reason"]).encode()
        ).hexdigest()
        grill_hash = hashlib.sha256(
            orjson.dumps(
                orjson.loads(row["grill_evidence_json"]) or [],
                option=orjson.OPT_SORT_KEYS,
            )
        ).hexdigest()
        identity = {
            "legacy_rollback_id": str(row["rollback_id"]),
            "graph_id": str(row["graph_id"]),
            "from_version": int(row["from_version"]),
            "to_version": int(row["to_version"]),
            "reason_hash": reason_hash,
        }
        descriptor_hash = hashlib.sha256(
            orjson.dumps(identity, option=orjson.OPT_SORT_KEYS)
        ).hexdigest()
        owner = owners[actor]
        case_id = "legacy-pointer-history-" + descriptor_hash[:24]
        changed = conn.execute(
            """
            INSERT OR IGNORE INTO research_maintenance_cases (
                case_id, owner_user_id, kind, descriptor_hash, status,
                affected_refs_json, change_refs_json, conversation_ref,
                claimed_agent_id, latest_result_ref, created_at, updated_at,
                claimed_at, closed_at
            ) VALUES (
                ?, ?, 'pointer_history', ?, 'resolved', ?, ?, '',
                ?, ?, ?, ?, ?, ?
            )
            """,
            (
                case_id,
                owner,
                descriptor_hash,
                orjson.dumps([
                    (
                        f"legacy-pointer-change:{identity['graph_id']}:"
                        f"{identity['from_version']}->{identity['to_version']}"
                    ),
                    f"legacy-reason-hash:{reason_hash}",
                ]).decode(),
                orjson.dumps([
                    f"legacy-rollback-id:{identity['legacy_rollback_id']}",
                    f"legacy-grill-evidence-hash:{grill_hash}",
                    "legacy-history:not-an-authorization",
                ]).decode(),
                f"migration:{actor}",
                f"legacy-rollback:{identity['legacy_rollback_id']}",
                float(row["created_at"]),
                float(row["created_at"]),
                float(row["created_at"]),
                float(row["created_at"]),
            ),
        ).rowcount
        inserted += max(int(changed), 0)
    return inserted


def _validate_pointer_targets(conn: Any) -> None:
    missing = conn.execute(
        """
        SELECT p.graph_id, p.version
        FROM active_research_graphs p
        LEFT JOIN research_graph_versions v
          ON v.graph_id=p.graph_id AND v.version=p.version
        WHERE v.graph_id IS NULL
        """
    ).fetchall()
    if missing:
        refs = [
            f"{row['graph_id']}@{int(row['version'])}"
            for row in missing
        ]
        raise ValueError(
            "active pointer references missing Graph version: "
            + ", ".join(refs)
        )


def _active_pointer_count(db_path: str | Path) -> int:
    with connect_sqlite(Path(db_path)) as conn:
        return int(conn.execute(
            "SELECT COUNT(*) FROM active_research_graphs"
        ).fetchone()[0])


def _table_names(conn: Any) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
    }


def _empty_report(started: float, table_count: int) -> dict[str, Any]:
    return {
        "active_pointers_validated": 0,
        "legacy_rollback_rows_projected": 0,
        "historical_cases_inserted": 0,
        "schema_tables_before": table_count,
        "schema_tables_after": table_count,
        "schema_tables_removed": 0,
        "transactions": 0,
        "rollback_target": (
            "restore pre-migration database backup and parent commit 2f793cc2"
        ),
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
    }
