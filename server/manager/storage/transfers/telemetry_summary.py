"""Bounded read-only aggregation for Manager-local transfer telemetry."""

from __future__ import annotations

import time

from server.manager.storage.transfers.telemetry_constants import (
    ACTIVE_STREAM_STALE_SECONDS,
)


def build_summary(
    store,
    *,
    object_kind: str = "",
    operation: str = "",
    since: float | None = None,
    until: float | None = None,
    now: float | None = None,
) -> dict[str, object]:
    current = time.time() if now is None else float(now)
    selected_until = current if until is None else min(float(until), current)
    selected_since = (
        selected_until - 24 * 60 * 60
        if since is None else float(since)
    )
    selected_since = max(selected_since, selected_until - 7 * 24 * 60 * 60)
    store.prune(now=current)
    filters, parameters = _filters(
        object_kind=object_kind,
        operation=operation,
        since=selected_since,
        until=selected_until,
    )
    active_filters, active_parameters = _active_filters(
        object_kind=object_kind,
        operation=operation,
        now=current,
    )
    with store._connect() as connection:
        totals = connection.execute(
            """
            SELECT COUNT(*) AS attempts,
                   COALESCE(SUM(transferred_bytes), 0) AS transferred_bytes,
                   COALESCE(SUM(expected_bytes), 0) AS expected_bytes,
                   COALESCE(SUM(duration_ms), 0) AS duration_ms,
                   COALESCE(AVG(duration_ms), 0) AS average_duration_ms,
                   COALESCE(SUM(CASE WHEN status != 'completed' THEN 1 ELSE 0 END), 0)
                       AS failed_attempts
            FROM transfer_telemetry
            WHERE """ + filters,
            parameters,
        ).fetchone()
        dimensions = connection.execute(
            """
            SELECT object_kind, operation, mode, surface, action,
                   COUNT(*) AS attempts,
                   COALESCE(SUM(transferred_bytes), 0) AS transferred_bytes,
                   COALESCE(SUM(expected_bytes), 0) AS expected_bytes,
                   COALESCE(SUM(duration_ms), 0) AS duration_ms,
                   COALESCE(SUM(CASE WHEN status != 'completed' THEN 1 ELSE 0 END), 0)
                       AS failed_attempts
            FROM transfer_telemetry
            WHERE """ + filters + """
            GROUP BY object_kind, operation, mode, surface, action
            ORDER BY transferred_bytes DESC, object_kind, operation
            LIMIT 100
            """,
            parameters,
        ).fetchall()
        failures = connection.execute(
            """
            SELECT failure_reason, COUNT(*) AS count
            FROM transfer_telemetry
            WHERE """ + filters + """
              AND status != 'completed'
              AND failure_reason != ''
            GROUP BY failure_reason
            ORDER BY count DESC, failure_reason
            LIMIT 20
            """,
            parameters,
        ).fetchall()
        active_total = connection.execute(
            "SELECT COUNT(*) AS count FROM transfer_active_streams WHERE "
            + active_filters,
            active_parameters,
        ).fetchone()["count"]
        active_dimensions = connection.execute(
            """
            SELECT object_kind, operation, mode, surface, action,
                   COUNT(*) AS active_connections,
                   COALESCE(SUM(transferred_bytes), 0) AS transferred_bytes,
                   COALESCE(SUM(expected_bytes), 0) AS expected_bytes
            FROM transfer_active_streams
            WHERE """ + active_filters + """
            GROUP BY object_kind, operation, mode, surface, action
            ORDER BY active_connections DESC, object_kind, operation
            LIMIT 100
            """,
            active_parameters,
        ).fetchall()
    return {
        "server_id": store.server_id,
        "window": {
            "since": selected_since,
            "until": selected_until,
        },
        "totals": _row(totals),
        "dimensions": [_row(value) for value in dimensions],
        "failure_reasons": [_row(value) for value in failures],
        "active": {
            "connections": int(active_total or 0),
            "dimensions": [_row(value) for value in active_dimensions],
        },
    }


def _filters(
    *, object_kind: str, operation: str, since: float, until: float,
) -> tuple[str, tuple[object, ...]]:
    clauses = ["started_at >= ?", "started_at <= ?"]
    values: list[object] = [since, until]
    if object_kind:
        clauses.append("object_kind = ?")
        values.append(str(object_kind))
    if operation:
        clauses.append("operation = ?")
        values.append(str(operation))
    return " AND ".join(clauses), tuple(values)


def _active_filters(
    *, object_kind: str, operation: str, now: float,
) -> tuple[str, tuple[object, ...]]:
    clauses = ["last_seen_at >= ?"]
    values: list[object] = [now - ACTIVE_STREAM_STALE_SECONDS]
    if object_kind:
        clauses.append("object_kind = ?")
        values.append(str(object_kind))
    if operation:
        clauses.append("operation = ?")
        values.append(str(operation))
    return " AND ".join(clauses), tuple(values)


def _row(value) -> dict[str, object]:
    return {key: value[key] for key in value.keys()}


__all__ = ["build_summary"]
