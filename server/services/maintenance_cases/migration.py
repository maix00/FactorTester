"""Explicit helpers for Batch2 import into the Maintenance Case owner."""

from __future__ import annotations

from typing import Any, Iterable

import sqlite3

from .backend_anomalies import backend_anomaly_case_spec
from .schema import connect_maintenance_cases, create_schema
from .store import MaintenanceCaseStore, open_case_in_connection


def migrate_backend_anomaly_rows(
    *,
    store: MaintenanceCaseStore,
    rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Idempotently import bounded legacy anomaly projections.

    The caller owns reading and deleting the legacy table in its integration
    transaction. Rows intentionally contain references and anomaly codes only.
    """
    with connect_maintenance_cases(store.db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        return migrate_backend_anomaly_rows_in_connection(
            conn=conn,
            rows=rows,
        )


def migrate_backend_anomaly_rows_in_connection(
    *,
    conn: sqlite3.Connection,
    rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Import cases inside the caller's Batch2 conversion transaction."""
    create_schema(conn)
    cases = []
    for row in rows:
        spec = backend_anomaly_case_spec(
            owner_user_id=str(row.get("owner_user_id") or ""),
            job_id=str(row.get("job_id") or ""),
            policy_hash=str(row.get("policy_hash") or ""),
            anomaly_codes=list(row.get("anomaly_codes") or []),
            conversation_ref=str(row.get("conversation_ref") or ""),
        )
        cases.append(open_case_in_connection(conn, **spec))
    return cases
