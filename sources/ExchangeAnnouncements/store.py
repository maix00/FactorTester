"""SQLite storage for the exchange_announcements data source."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Iterable, Mapping
from typing import Any

from tools.data.field_history import _ensure_store_registered
from tools.data.field_history_agent_ingest import requester_key_fingerprint
from tools.data.hub import DataHub


EXCHANGE_ANNOUNCEMENTS_TABLE = "exchange_announcements"
LIST_FIELDS = ("field_groups", "field_names", "products", "contracts")


def append_exchange_announcements(
    rows: Iterable[Mapping[str, Any]],
    *,
    store_key: str = "openctp",
    requester_key: str = "",
    requester_key_hash: str = "",
) -> dict[str, int | str]:
    """Append announcement catalog rows directly to SQLite.

    Existing rows with the same content hash are skipped. Existing rows with the
    same announcement_id but different content raise for manual review.
    """
    if not requester_key and not requester_key_hash:
        raise ValueError("provide requester_key or requester_key_hash")
    fingerprint = requester_key_hash or requester_key_fingerprint(requester_key)
    normalised = [_normalise_row(row) for row in rows]
    hub = DataHub.get_instance()
    _ensure_store_registered(hub, store_key)
    inserted = 0
    skipped = 0
    with hub.connect_store(store_key) as conn:
        ensure_exchange_announcements_schema(conn)
        for row in normalised:
            if _announcement_exists(conn, row):
                skipped += 1
                continue
            _insert_announcement(conn, row, requester_key_hash=fingerprint)
            inserted += 1
    return {
        "table": EXCHANGE_ANNOUNCEMENTS_TABLE,
        "candidate_announcements": len(normalised),
        "inserted_announcements": inserted,
        "skipped_existing": skipped,
    }


def ensure_exchange_announcements_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {EXCHANGE_ANNOUNCEMENTS_TABLE} (
            announcement_id TEXT PRIMARY KEY,
            exchange TEXT NOT NULL,
            source_url TEXT NOT NULL,
            source_accessed_at TEXT NOT NULL,
            published_date TEXT,
            notice_id TEXT,
            title TEXT NOT NULL,
            category TEXT,
            summary TEXT,
            raw_text TEXT,
            content_hash TEXT NOT NULL,
            field_change_candidate INTEGER NOT NULL,
            field_groups_json TEXT NOT NULL,
            field_names_json TEXT NOT NULL,
            products_json TEXT NOT NULL,
            contracts_json TEXT NOT NULL,
            parser_notes TEXT,
            agent_name TEXT,
            requester_key_hash TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{EXCHANGE_ANNOUNCEMENTS_TABLE}_exchange_date
        ON {EXCHANGE_ANNOUNCEMENTS_TABLE}(exchange, published_date)
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{EXCHANGE_ANNOUNCEMENTS_TABLE}_field_candidate
        ON {EXCHANGE_ANNOUNCEMENTS_TABLE}(field_change_candidate)
        """
    )


def _normalise_row(row: Mapping[str, Any]) -> dict[str, Any]:
    item = dict(row)
    required = ("announcement_id", "exchange", "source_url", "source_accessed_at", "title")
    missing = [key for key in required if key not in item or item[key] in (None, "")]
    if missing:
        raise ValueError(f"exchange announcement missing required keys: {', '.join(missing)}")
    for key in LIST_FIELDS:
        value = item.get(key, [])
        if value is None:
            item[key] = []
        elif not isinstance(value, list):
            raise ValueError(f"{key} must be a list")
        else:
            item[key] = [str(part) for part in value]
    item["field_change_candidate"] = bool(item.get("field_change_candidate"))
    return item


def _announcement_exists(conn: sqlite3.Connection, row: Mapping[str, Any]) -> bool:
    existing = conn.execute(
        f"""
        SELECT content_hash
        FROM {EXCHANGE_ANNOUNCEMENTS_TABLE}
        WHERE announcement_id = ?
        """,
        (row["announcement_id"],),
    ).fetchone()
    if existing is None:
        return False
    old_hash = str(existing["content_hash"])
    new_hash = content_hash(row)
    if old_hash != new_hash:
        raise ValueError(
            f"exchange announcement content changed for {row['announcement_id']}: "
            f"existing={old_hash} new={new_hash}"
        )
    return True


def _insert_announcement(conn: sqlite3.Connection, row: Mapping[str, Any], *, requester_key_hash: str) -> None:
    conn.execute(
        f"""
        INSERT INTO {EXCHANGE_ANNOUNCEMENTS_TABLE}
        (announcement_id, exchange, source_url, source_accessed_at, published_date,
         notice_id, title, category, summary, raw_text, content_hash,
         field_change_candidate, field_groups_json, field_names_json, products_json,
         contracts_json, parser_notes, agent_name, requester_key_hash, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(row["announcement_id"]),
            str(row["exchange"]),
            str(row["source_url"]),
            str(row["source_accessed_at"]),
            str(row.get("published_date") or ""),
            str(row.get("notice_id") or ""),
            str(row["title"]),
            str(row.get("category") or ""),
            str(row.get("summary") or ""),
            str(row.get("raw_text") or ""),
            content_hash(row),
            1 if bool(row.get("field_change_candidate")) else 0,
            _json_list(row.get("field_groups")),
            _json_list(row.get("field_names")),
            _json_list(row.get("products")),
            _json_list(row.get("contracts")),
            str(row.get("parser_notes") or ""),
            str(row.get("agent_name") or ""),
            requester_key_hash,
            time.time(),
        ),
    )


def content_hash(row: Mapping[str, Any]) -> str:
    content = {
        "exchange": row.get("exchange") or "",
        "source_url": row.get("source_url") or "",
        "published_date": row.get("published_date") or "",
        "notice_id": row.get("notice_id") or "",
        "title": row.get("title") or "",
        "category": row.get("category") or "",
        "summary": row.get("summary") or "",
        "raw_text": row.get("raw_text") or "",
        "field_change_candidate": bool(row.get("field_change_candidate")),
        "field_groups": row.get("field_groups") or [],
        "field_names": row.get("field_names") or [],
        "products": row.get("products") or [],
        "contracts": row.get("contracts") or [],
    }
    payload = json.dumps(content, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_list(value: Any) -> str:
    if value is None:
        return "[]"
    if not isinstance(value, list):
        raise TypeError("expected list")
    return json.dumps([str(item) for item in value], ensure_ascii=False)
