"""Append-only agent ingestion for historical field-change events.

This is the controlled path for human/agent data cleaning. Agents write an
auditable event list derived from source URLs and natural language. The table is
append-only by API: no helper in this module deletes or updates submitted
events. A separate materialization step copies validated rows into
``historical_field_values`` with per-event source keys, so existing provider
rows are not overwritten.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from tools.data.field_history import save_historical_field_records
from tools.data.hub import DataHub


AGENT_EVENT_TABLE = "agent_field_change_events"
_KEY_HASH_VERSION = "hmac-sha256-v1"


@dataclass(frozen=True, slots=True)
class AgentFieldChangeEvent:
    data_source: str
    field_group: str
    source_url: str
    source_accessed_at: str
    agent_name: str
    requester_key_hash: str
    instrument: str
    instrument_label: str
    instrument_type: str
    field_name: str
    effective_trading_day: str
    value: Any
    contract_codes: tuple[str, ...] = ()
    contract_scope_type: str = ""
    contract_code_start: str = ""
    contract_code_end: str = ""
    change_type: str = "change"
    effective_timestamp: str = ""
    source_notice_id: str = ""
    raw_note: str = ""
    evidence_text: str = ""
    parser_notes: str = ""
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)


def requester_key_fingerprint(requester_key: str) -> str:
    """Return a non-reversible fingerprint for a human requester key.

    The raw key must not be stored. If ``GTHT_AGENT_INGEST_HMAC_SECRET`` is set,
    the fingerprint is HMAC'd with that secret; otherwise it falls back to a
    namespaced SHA-256 hash for local development.
    """
    text = str(requester_key or "")
    secret = os.environ.get("GTHT_AGENT_INGEST_HMAC_SECRET")
    if secret:
        digest = hmac.new(secret.encode("utf-8"), text.encode("utf-8"), hashlib.sha256).hexdigest()
    else:
        digest = hashlib.sha256(f"gtht-agent-ingest-v1:{text}".encode("utf-8")).hexdigest()
    return f"{_KEY_HASH_VERSION}:{digest}"


def append_agent_field_change_events(
    events: Iterable[AgentFieldChangeEvent | Mapping[str, Any]],
    *,
    store_key: str = "openctp",
) -> list[str]:
    """Append agent-cleaned events and return event ids."""
    normalised = [_normalise_agent_event(event) for event in events]
    if not normalised:
        return []
    hub = DataHub.get_instance()
    hub.ensure_visits_schema()
    with hub.connect_store(store_key) as conn:
        ensure_agent_event_schema(conn)
        conn.executemany(
            f"""
            INSERT INTO {AGENT_EVENT_TABLE}
            (event_id, data_source, field_group, source_url, source_accessed_at,
             agent_name, requester_key_hash, instrument, instrument_label,
             instrument_type, field_name, effective_trading_day, effective_timestamp,
             value_json, contract_codes_json, contract_scope_type, contract_code_start,
             contract_code_end, change_type, source_notice_id, raw_note,
             evidence_text, parser_notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [_event_row(event) for event in normalised],
        )
    return [event.event_id for event in normalised]


def materialize_agent_events_to_history(
    *,
    store_key: str = "openctp",
    data_source: str | None = None,
    field_group: str | None = None,
) -> int:
    """Copy append-only agent events into historical_field_values.

    Each event gets source_key ``agent/<data_source>/<event_id>`` so
    materialization does not replace unrelated source rows.
    """
    hub = DataHub.get_instance()
    hub.ensure_visits_schema()
    with hub.connect_store(store_key) as conn:
        ensure_agent_event_schema(conn)
        clauses: list[str] = []
        params: list[Any] = []
        if data_source:
            clauses.append("data_source = ?")
            params.append(data_source)
        if field_group:
            clauses.append("field_group = ?")
            params.append(field_group)
        sql = f"SELECT * FROM {AGENT_EVENT_TABLE}"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        rows = conn.execute(sql, params).fetchall()
    records = [_history_record_from_agent_row(row) for row in rows]
    save_historical_field_records(records, store_key=store_key)
    return len(records)


def ensure_agent_event_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {AGENT_EVENT_TABLE} (
            event_id TEXT PRIMARY KEY,
            data_source TEXT NOT NULL,
            field_group TEXT NOT NULL,
            source_url TEXT NOT NULL,
            source_accessed_at TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            requester_key_hash TEXT NOT NULL,
            instrument TEXT NOT NULL,
            instrument_label TEXT,
            instrument_type TEXT NOT NULL,
            field_name TEXT NOT NULL,
            effective_trading_day TEXT NOT NULL,
            effective_timestamp TEXT,
            value_json TEXT NOT NULL,
            contract_codes_json TEXT NOT NULL,
            contract_scope_type TEXT NOT NULL DEFAULT 'all',
            contract_code_start TEXT,
            contract_code_end TEXT,
            change_type TEXT NOT NULL DEFAULT 'change',
            source_notice_id TEXT,
            raw_note TEXT,
            evidence_text TEXT,
            parser_notes TEXT,
            created_at REAL NOT NULL
        )
        """
    )
    existing_columns = {
        row["name"]
        for row in conn.execute(f'PRAGMA table_info("{AGENT_EVENT_TABLE}")').fetchall()
    }
    if "contract_scope_type" not in existing_columns:
        conn.execute(f'ALTER TABLE "{AGENT_EVENT_TABLE}" ADD COLUMN contract_scope_type TEXT NOT NULL DEFAULT "all"')
    if "contract_code_start" not in existing_columns:
        conn.execute(f'ALTER TABLE "{AGENT_EVENT_TABLE}" ADD COLUMN contract_code_start TEXT')
    if "contract_code_end" not in existing_columns:
        conn.execute(f'ALTER TABLE "{AGENT_EVENT_TABLE}" ADD COLUMN contract_code_end TEXT')
    if "change_type" not in existing_columns:
        conn.execute(f'ALTER TABLE "{AGENT_EVENT_TABLE}" ADD COLUMN change_type TEXT NOT NULL DEFAULT "change"')
    conn.execute(
        f"""
        UPDATE {AGENT_EVENT_TABLE}
        SET contract_scope_type = 'explicit'
        WHERE COALESCE(contract_scope_type, '') IN ('', 'all')
          AND COALESCE(contract_codes_json, '') NOT IN ('', '[]')
        """
    )
    conn.execute(
        f"""
        UPDATE {AGENT_EVENT_TABLE}
        SET contract_scope_type = CASE
            WHEN COALESCE(contract_code_end, '') != '' THEN 'range'
            ELSE 'from_contract'
        END
        WHERE COALESCE(contract_scope_type, '') IN ('', 'all')
          AND COALESCE(contract_code_start, '') != ''
        """
    )


def _normalise_agent_event(event: AgentFieldChangeEvent | Mapping[str, Any]) -> AgentFieldChangeEvent:
    if isinstance(event, AgentFieldChangeEvent):
        return event
    requester_hash = str(event.get("requester_key_hash") or "")
    requester_key = str(event.get("requester_key") or "")
    if not requester_hash:
        if not requester_key:
            raise ValueError("agent event requires requester_key_hash or requester_key")
        requester_hash = requester_key_fingerprint(requester_key)
    contract_codes = tuple(str(code) for code in event.get("contract_codes", ()))
    return AgentFieldChangeEvent(
        event_id=str(event.get("event_id") or uuid.uuid4().hex),
        data_source=str(event["data_source"]),
        field_group=str(event["field_group"]),
        source_url=str(event["source_url"]),
        source_accessed_at=str(event["source_accessed_at"]),
        agent_name=str(event["agent_name"]),
        requester_key_hash=requester_hash,
        instrument=str(event["instrument"]).upper(),
        instrument_label=str(event.get("instrument_label") or ""),
        instrument_type=str(event.get("instrument_type") or "future"),
        field_name=str(event["field_name"]),
        effective_trading_day=str(event["effective_trading_day"]),
        effective_timestamp=str(event.get("effective_timestamp") or ""),
        value=event["value"],
        contract_codes=contract_codes,
        contract_scope_type=str(event.get("contract_scope_type") or ""),
        contract_code_start=str(event.get("contract_code_start") or ""),
        contract_code_end=str(event.get("contract_code_end") or ""),
        change_type=str(event.get("change_type") or "change"),
        source_notice_id=str(event.get("source_notice_id") or ""),
        raw_note=str(event.get("raw_note") or ""),
        evidence_text=str(event.get("evidence_text") or ""),
        parser_notes=str(event.get("parser_notes") or ""),
    )


def _event_row(event: AgentFieldChangeEvent) -> tuple[Any, ...]:
    return (
        event.event_id,
        event.data_source,
        event.field_group,
        event.source_url,
        event.source_accessed_at,
        event.agent_name,
        event.requester_key_hash,
        event.instrument,
        event.instrument_label,
        event.instrument_type,
        event.field_name,
        event.effective_trading_day,
        event.effective_timestamp,
        json.dumps(event.value, ensure_ascii=False),
        json.dumps(list(event.contract_codes), ensure_ascii=False),
        event.contract_scope_type,
        event.contract_code_start,
        event.contract_code_end,
        event.change_type,
        event.source_notice_id,
        event.raw_note,
        event.evidence_text,
        event.parser_notes,
        time.time(),
    )


def _history_record_from_agent_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "provider": f"Agent:{row['data_source']}",
        "source_key": f"agent/{row['data_source']}/{row['event_id']}",
        "instrument": row["instrument"],
        "instrument_label": row["instrument_label"],
        "instrument_type": row["instrument_type"],
        "field_name": row["field_name"],
        "effective_trading_day": row["effective_trading_day"],
        "effective_timestamp": row["effective_timestamp"],
        "value": json.loads(row["value_json"]),
        "contract_codes": json.loads(row["contract_codes_json"]),
        "contract_scope_type": row["contract_scope_type"],
        "contract_code_start": row["contract_code_start"],
        "contract_code_end": row["contract_code_end"],
        "change_type": row["change_type"],
        "source_url": row["source_url"],
        "source_date": row["source_accessed_at"],
        "source_notice_id": row["source_notice_id"],
        "raw_note": row["raw_note"],
    }
