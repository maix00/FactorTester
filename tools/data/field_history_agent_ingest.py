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
from datetime import date, datetime, timedelta
from typing import Any

from tools.data.field_history import (
    FieldHistoryProvider,
    HistoricalFieldLookupError,
    load_historical_field_frame,
    save_historical_field_records,
)
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
    scope_type: str = "product"
    exchange: str = ""
    contract_codes: tuple[str, ...] = ()
    contract_scope_type: str = ""
    contract_code_start: str = ""
    contract_code_end: str = ""
    change_type: str = "change"
    effective_timestamp: str = ""
    previous_value: Any = None
    previous_value_type: str = ""
    previous_value_note: str = ""
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
             instrument_type, scope_type, exchange, field_name, effective_trading_day, effective_timestamp,
             value_json, previous_value_json, previous_value_type, previous_value_note,
             contract_codes_json, contract_scope_type, contract_code_start,
             contract_code_end, change_type, source_notice_id, raw_note,
             evidence_text, parser_notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def audit_agent_event_previous_values(
    *,
    store_key: str = "openctp",
    data_source: str | None = None,
    field_group: str | None = None,
) -> list[dict[str, Any]]:
    """Return continuity issues for agent events that declare previous_value.

    This is intentionally an audit step, not an ingestion gate: source events
    are allowed to land first, then integrity tests can report rows whose
    declared previous value does not match the materialized history.
    """
    hub = DataHub.get_instance()
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
    return _previous_value_issues(records, store_key=store_key)


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
            scope_type TEXT NOT NULL DEFAULT 'product',
            exchange TEXT,
            field_name TEXT NOT NULL,
            effective_trading_day TEXT NOT NULL,
            effective_timestamp TEXT,
            value_json TEXT NOT NULL,
            previous_value_json TEXT,
            previous_value_type TEXT,
            previous_value_note TEXT,
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
    if "scope_type" not in existing_columns:
        conn.execute(f'ALTER TABLE "{AGENT_EVENT_TABLE}" ADD COLUMN scope_type TEXT NOT NULL DEFAULT "product"')
    if "exchange" not in existing_columns:
        conn.execute(f'ALTER TABLE "{AGENT_EVENT_TABLE}" ADD COLUMN exchange TEXT')
    if "contract_code_start" not in existing_columns:
        conn.execute(f'ALTER TABLE "{AGENT_EVENT_TABLE}" ADD COLUMN contract_code_start TEXT')
    if "contract_code_end" not in existing_columns:
        conn.execute(f'ALTER TABLE "{AGENT_EVENT_TABLE}" ADD COLUMN contract_code_end TEXT')
    if "change_type" not in existing_columns:
        conn.execute(f'ALTER TABLE "{AGENT_EVENT_TABLE}" ADD COLUMN change_type TEXT NOT NULL DEFAULT "change"')
    if "previous_value_json" not in existing_columns:
        conn.execute(f'ALTER TABLE "{AGENT_EVENT_TABLE}" ADD COLUMN previous_value_json TEXT')
    if "previous_value_type" not in existing_columns:
        conn.execute(f'ALTER TABLE "{AGENT_EVENT_TABLE}" ADD COLUMN previous_value_type TEXT')
    if "previous_value_note" not in existing_columns:
        conn.execute(f'ALTER TABLE "{AGENT_EVENT_TABLE}" ADD COLUMN previous_value_note TEXT')
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
    effective_timestamp = str(event.get("effective_timestamp") or "").strip()
    if not effective_timestamp:
        effective_timestamp = _infer_effective_timestamp(event)
    _validate_event_semantics(event)
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
        scope_type=str(event.get("scope_type") or "product").strip().lower(),
        exchange=str(event.get("exchange") or "").strip().upper(),
        field_name=str(event["field_name"]),
        effective_trading_day=str(event["effective_trading_day"]),
        effective_timestamp=effective_timestamp,
        previous_value=event.get("previous_value"),
        previous_value_type=str(event.get("previous_value_type") or ""),
        previous_value_note=str(event.get("previous_value_note") or ""),
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


def _validate_event_semantics(event: Mapping[str, Any]) -> None:
    """Reject event payloads that contradict settled exchange-rule semantics."""
    field_name = str(event.get("field_name") or "")
    if field_name not in {"CloseTodayRatioByMoney", "CloseTodayRatioByVolume"}:
        return
    text = " ".join(
        str(event.get(key) or "")
        for key in ("raw_note", "evidence_text", "parser_notes")
    )
    if "日内开平仓手续费减半" not in text and "当日开平仓手续费减半" not in text:
        return
    if any(token in text for token in ("取消", "不再", "恢复")):
        return
    try:
        value = float(event.get("value"))
    except (TypeError, ValueError):
        return
    if abs(value) > 1e-12:
        raise ValueError(
            "close-today fee must be 0 when source says 日内/当日开平仓手续费减半; "
            f"got {value!r} for {event.get('instrument')}.{field_name}"
        )


def _infer_effective_timestamp(event: Mapping[str, Any]) -> str:
    """Infer exchange-rule effective timestamp from explicit session metadata.

    ``effective_trading_day`` is a trading-day label.  For Chinese futures,
    night-session changes belong to the next trading day but start on the
    previous calendar day at night open.  This helper only infers when an event
    explicitly declares ``effective_session``; otherwise it leaves the timestamp
    blank so audit scripts can flag the row for source-level review.
    """
    session = str(event.get("effective_session") or "").strip().lower()
    if not session:
        return ""
    trading_day = _parse_iso_date(str(event.get("effective_trading_day") or ""))
    if session in {"day", "day_open", "日盘", "日盘开盘"}:
        return f"{trading_day.isoformat()} 09:00:00"
    if session in {"night", "night_open", "夜盘", "夜盘开盘"}:
        night_day = trading_day - timedelta(days=1)
        return f"{night_day.isoformat()} 21:00:00"
    raise ValueError(f"unsupported effective_session={session!r}; expected day or night")


def _parse_iso_date(value: str) -> date:
    text = value.strip()
    if not text:
        raise ValueError("effective_session inference requires effective_trading_day")
    return datetime.fromisoformat(text[:10]).date()


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
        event.scope_type,
        event.exchange,
        event.field_name,
        event.effective_trading_day,
        event.effective_timestamp,
        json.dumps(event.value, ensure_ascii=False),
        "" if event.previous_value is None else json.dumps(event.previous_value, ensure_ascii=False),
        event.previous_value_type,
        event.previous_value_note,
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
        "scope_type": row["scope_type"],
        "exchange": row["exchange"],
        "field_name": row["field_name"],
        "effective_trading_day": row["effective_trading_day"],
        "effective_timestamp": row["effective_timestamp"],
        "value": json.loads(row["value_json"]),
        "previous_value": _loads_optional_json(row["previous_value_json"]),
        "previous_value_type": row["previous_value_type"],
        "previous_value_note": row["previous_value_note"],
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


def _loads_optional_json(value: Any) -> Any:
    text = str(value or "").strip()
    if not text:
        return None
    return json.loads(text)


def _previous_value_issues(records: list[dict[str, Any]], *, store_key: str) -> list[dict[str, Any]]:
    records_with_previous = [record for record in records if _has_previous_value(record)]
    if not records_with_previous:
        return []
    historical = load_historical_field_frame(store_key=store_key)
    accepted: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for record in sorted(records, key=_record_effective_key):
        if _has_previous_value(record):
            prior = _previous_record_for(record, historical, accepted)
            if prior is None:
                issues.append(_previous_value_issue(record, "missing_prior", "no prior historical value", None))
            else:
                expected = record["previous_value"]
                actual = prior.get("value")
                if not _same_value(actual, expected):
                    issues.append(_previous_value_issue(
                        record,
                        "previous_value_mismatch",
                        f"expected {expected!r}, found {actual!r}",
                        prior,
                    ))
        accepted.append(record)
    return issues


def _has_previous_value(record: Mapping[str, Any]) -> bool:
    value = record.get("previous_value")
    if value is None:
        return False
    if isinstance(value, str) and value.strip() == "":
        return False
    return True


def _previous_record_for(
    record: Mapping[str, Any],
    historical: Any,
    accepted: list[dict[str, Any]],
) -> dict[str, Any] | None:
    import pandas as pd

    current_day = _record_effective_day(record)
    frames = []
    if historical is not None and not historical.empty:
        frames.append(historical)
    if accepted:
        prior_accepted = [
            candidate
            for candidate in accepted
            if _record_effective_day(candidate) < current_day
        ]
        if prior_accepted:
            frames.append(pd.DataFrame(prior_accepted))
    if not frames:
        return None
    provider = FieldHistoryProvider(pd.concat(frames, ignore_index=True, sort=False))
    try:
        subset = provider._subset(  # noqa: SLF001 - validation intentionally reuses provider scope semantics.
            str(record.get("instrument") or "").upper(),
            str(record.get("field_name") or ""),
            str(record.get("instrument_type") or "future"),
            exchange=str(record.get("exchange") or "") or None,
        )
    except HistoricalFieldLookupError:
        return None
    candidates = []
    for _, row in subset.iterrows():
        candidate = dict(row)
        if _record_source_key(candidate) == _record_source_key(record):
            continue
        if _record_effective_day(candidate) >= current_day:
            continue
        if not _scope_covers(candidate, record):
            continue
        candidates.append(candidate)
    if not candidates:
        return None
    return sorted(candidates, key=_record_effective_key)[-1]


def _scope_covers(prior: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    current_codes = _contract_codes(current)
    if not current_codes:
        return str(prior.get("contract_scope_type") or "all").lower() == "all"
    return all(_scope_covers_code(prior, code) for code in current_codes)


def _scope_covers_code(prior: Mapping[str, Any], code: str) -> bool:
    scope = str(prior.get("contract_scope_type") or "all").lower()
    if scope == "all":
        return True
    codes = _contract_codes(prior)
    if scope == "explicit":
        return code in codes
    start = str(prior.get("contract_code_start") or "").upper()
    end = str(prior.get("contract_code_end") or "").upper()
    if scope == "from_contract":
        return bool(start) and code >= start
    if scope == "range":
        return bool(start and end) and start <= code <= end
    return False


def _contract_codes(record: Mapping[str, Any]) -> list[str]:
    raw = record.get("contract_codes")
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            raw = [part.strip() for part in text.split(",") if part.strip()]
    if not raw:
        return []
    return [str(code).upper() for code in raw]


def _record_effective_key(record: Mapping[str, Any]) -> tuple[Any, Any]:
    import pandas as pd

    day = _record_effective_day(record)
    ts_raw = str(record.get("effective_timestamp") or "").strip()
    ts = pd.Timestamp(ts_raw) if ts_raw else day
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return day, ts


def _record_effective_day(record: Mapping[str, Any]) -> Any:
    import pandas as pd

    return pd.Timestamp(record.get("effective_trading_day")).normalize()


def _record_source_key(record: Mapping[str, Any]) -> str:
    source_key = str(record.get("source_key") or "")
    if source_key:
        return source_key
    return f"agent/{record.get('data_source')}/{record.get('event_id')}"


def _same_value(left: Any, right: Any) -> bool:
    try:
        return abs(float(left) - float(right)) <= 1e-12
    except (TypeError, ValueError):
        return str(left) == str(right)


def _previous_value_error(record: Mapping[str, Any], reason: str) -> str:
    return (
        "historical field previous_value validation failed: "
        f"{record.get('instrument')}.{record.get('field_name')} "
        f"effective={record.get('effective_trading_day')} "
        f"notice={record.get('source_notice_id') or record.get('event_id')}: {reason}"
    )


def _previous_value_issue(
    record: Mapping[str, Any],
    status: str,
    reason: str,
    prior: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "status": status,
        "instrument": str(record.get("instrument") or ""),
        "field_name": str(record.get("field_name") or ""),
        "effective_trading_day": str(record.get("effective_trading_day") or ""),
        "effective_timestamp": str(record.get("effective_timestamp") or ""),
        "source_key": _record_source_key(record),
        "source_notice_id": str(record.get("source_notice_id") or ""),
        "previous_value": record.get("previous_value"),
        "prior_value": None if prior is None else prior.get("value"),
        "prior_source_key": "" if prior is None else str(prior.get("source_key") or ""),
        "prior_source_notice_id": "" if prior is None else str(prior.get("source_notice_id") or ""),
        "reason": reason,
        "message": _previous_value_error(record, reason),
    }
