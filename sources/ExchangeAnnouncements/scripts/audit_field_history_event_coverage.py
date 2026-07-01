"""Audit whether field-change candidate announcements have FieldHistory events."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from sources.ExchangeAnnouncements.store import (
    EXCHANGE_ANNOUNCEMENTS_TABLE,
    ensure_exchange_announcements_schema,
)
from tools.data.field_history import _ensure_store_registered
from tools.data.field_history_agent_ingest import AGENT_EVENT_TABLE, ensure_agent_event_schema
from tools.data.hub import DataHub


def main() -> int:
    hub = DataHub.get_instance()
    _ensure_store_registered(hub, "openctp")
    with hub.connect_store("openctp") as conn:
        ensure_exchange_announcements_schema(conn)
        ensure_agent_event_schema(conn)
        rows = conn.execute(
            f"""
            SELECT *
            FROM {EXCHANGE_ANNOUNCEMENTS_TABLE}
            WHERE field_change_candidate = 1
            ORDER BY exchange, published_date, announcement_id
            """
        ).fetchall()
        audit = [_audit_row(conn, row) for row in rows]
    missing = [row for row in audit if not row["has_field_history_event"]]
    print(json.dumps({
        "candidate_announcements": len(audit),
        "covered_announcements": len(audit) - len(missing),
        "missing_announcements": len(missing),
        "missing": missing,
    }, ensure_ascii=False, indent=2))
    return 1 if missing else 0


def _audit_row(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    notice_id = str(row["notice_id"] or "")
    source_url = str(row["source_url"] or "")
    params: list[Any] = []
    predicates: list[str] = []
    if notice_id:
        predicates.append("source_notice_id = ?")
        params.append(notice_id)
    if source_url:
        predicates.append("source_url = ?")
        params.append(source_url)
    count = 0
    if predicates:
        sql = f"""
            SELECT COUNT(*) AS n
            FROM {AGENT_EVENT_TABLE}
            WHERE {" OR ".join(predicates)}
        """
        count = int(conn.execute(sql, params).fetchone()["n"])
    return {
        "announcement_id": row["announcement_id"],
        "exchange": row["exchange"],
        "notice_id": row["notice_id"],
        "title": row["title"],
        "field_groups": json.loads(row["field_groups_json"] or "[]"),
        "field_names": json.loads(row["field_names_json"] or "[]"),
        "products": json.loads(row["products_json"] or "[]"),
        "contracts": json.loads(row["contracts_json"] or "[]"),
        "event_count": count,
        "has_field_history_event": count > 0,
    }


if __name__ == "__main__":
    raise SystemExit(main())
