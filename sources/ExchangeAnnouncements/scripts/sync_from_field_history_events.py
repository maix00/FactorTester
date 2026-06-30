"""Seed exchange_announcements from already-ingested FieldHistory events.

This is a bridge for existing cleaned FieldHistory data. Future crawlers should
write every exchange announcement directly through
``sources.ExchangeAnnouncements.store.append_exchange_announcements`` first,
including announcements that do not contain field-value changes.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from typing import Any

from sources.ExchangeAnnouncements.store import append_exchange_announcements
from tools.data.field_history import _ensure_store_registered
from tools.data.field_history_agent_ingest import AGENT_EVENT_TABLE, ensure_agent_event_schema
from tools.data.hub import DataHub


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build exchange_announcements rows from existing agent field events")
    parser.add_argument("--store-key", default="openctp")
    parser.add_argument("--requester-key", default="")
    parser.add_argument("--requester-key-hash", default="")
    parser.add_argument("--field-group", default="")
    args = parser.parse_args(argv)
    rows = _announcement_rows_from_agent_events(store_key=args.store_key, field_group=args.field_group)
    result = append_exchange_announcements(
        rows,
        store_key=args.store_key,
        requester_key=args.requester_key,
        requester_key_hash=args.requester_key_hash,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _announcement_rows_from_agent_events(*, store_key: str, field_group: str = "") -> list[dict[str, Any]]:
    hub = DataHub.get_instance()
    _ensure_store_registered(hub, store_key)
    with hub.connect_store(store_key) as conn:
        ensure_agent_event_schema(conn)
        clauses: list[str] = []
        params: list[Any] = []
        if field_group:
            clauses.append("field_group = ?")
            params.append(field_group)
        sql = f"SELECT * FROM {AGENT_EVENT_TABLE}"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        events = conn.execute(sql, params).fetchall()
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        notice_key = str(event["source_notice_id"] or event["source_url"])
        key = (str(event["data_source"]), notice_key)
        row = grouped.setdefault(key, {
            "announcement_id": f"{event['data_source']}:{notice_key}",
            "exchange": str(event["data_source"]),
            "source_url": str(event["source_url"]),
            "source_accessed_at": str(event["source_accessed_at"]),
            "published_date": str(event["effective_trading_day"] or ""),
            "notice_id": str(event["source_notice_id"] or ""),
            "title": "",
            "category": "交易所公告",
            "summary": "",
            "raw_text": "",
            "field_change_candidate": True,
            "field_groups": set(),
            "field_names": set(),
            "products": set(),
            "contracts": set(),
            "parser_notes": "",
            "agent_name": str(event["agent_name"] or ""),
        })
        row["field_groups"].add(str(event["field_group"]))
        row["field_names"].add(str(event["field_name"]))
        row["products"].add(str(event["instrument"]))
        for contract_code in json.loads(event["contract_codes_json"] or "[]"):
            row["contracts"].add(f"{event['instrument']}{contract_code}")
        raw_note = str(event["raw_note"] or "")
        if len(raw_note) > len(str(row["raw_text"])):
            row["raw_text"] = raw_note
            row["summary"] = raw_note
        parser_notes = [str(row.get("parser_notes") or ""), str(event["parser_notes"] or "")]
        row["parser_notes"] = "；".join(dict.fromkeys([note for note in parser_notes if note]))
        if not row["published_date"] or str(event["effective_trading_day"] or "") < row["published_date"]:
            row["published_date"] = str(event["effective_trading_day"] or "")
    result: list[dict[str, Any]] = []
    for row in grouped.values():
        products = sorted(row["products"])
        row["title"] = f"{row['notice_id'] or row['exchange']} {'、'.join(products)} 字段值变更公告"
        for list_field in ("field_groups", "field_names", "products", "contracts"):
            row[list_field] = sorted(row[list_field])
        result.append(row)
    return sorted(result, key=lambda item: (item["exchange"], item["published_date"], item["announcement_id"]))


if __name__ == "__main__":
    raise SystemExit(main())
