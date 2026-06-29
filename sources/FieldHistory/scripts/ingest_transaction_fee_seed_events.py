"""Seed official transaction-fee field-change events.

This script is intentionally small and auditable: it stores agent-cleaned
events from official exchange notices through the append-only FieldHistory agent
ingest API, then materializes and rebuilds the TransactionFee unified view.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from hashlib import sha1
from typing import Any

from tools.data.field_history import HISTORICAL_FIELD_TABLE, _ensure_store_registered
from tools.data.field_history_agent_ingest import (
    AGENT_EVENT_TABLE,
    append_agent_field_change_events,
    ensure_agent_event_schema,
    materialize_agent_events_to_history,
)
from tools.data.hub import DataHub
from sources.FieldHistory.views.TransactionFee import save_unified_table


SOURCE_ACCESSED_AT = "2026-06-30T00:00:00+08:00"
AGENT_NAME = "codex"
REQUESTER_KEY = "issue-114-transaction-fee-seed"
FIELD_GROUP = "TransactionFee"


def main() -> int:
    events = list(_seed_events())
    hub = DataHub.get_instance()
    _ensure_store_registered(hub, "openctp")
    with hub.connect_store("openctp") as conn:
        ensure_agent_event_schema(conn)
        missing = [event for event in events if not _event_exists(conn, event)]
    if missing:
        append_agent_field_change_events(missing)
    materialize_agent_events_to_history(field_group=FIELD_GROUP)
    db_path = save_unified_table()
    print(json.dumps({
        "database": db_path,
        "candidate_events": len(events),
        "inserted_events": len(missing),
    }, ensure_ascii=False, indent=2))
    return 0


def _seed_events() -> Iterable[dict[str, Any]]:
    # GFEX official notice: 广期所发〔2025〕317号.
    # Effective from 2025-11-20 trading. LC2601 transaction fee and intraday
    # close-today fee were adjusted to 0.012% of turnover.
    yield from _contract_money_fee_events(
        data_source="GFEX",
        source_url="https://www.gfex.com.cn/gfex/tzts/202511/",
        source_notice_id="广期所发〔2025〕317号",
        instrument="LC",
        instrument_label="碳酸锂",
        effective_trading_day="2025-11-20",
        effective_timestamp="",
        contract_code="2601",
        money_ratio=0.00012,
        raw_note="自2025年11月20日交易时起，碳酸锂期货LC2601合约的交易手续费标准和日内平今仓交易手续费标准调整为成交金额的万分之一点二。",
        evidence_text="碳酸锂期货LC2601合约；交易手续费标准和日内平今仓交易手续费标准；成交金额的万分之一点二。",
        parser_notes="交易手续费标准映射开仓/普通平仓，日内平今仓交易手续费标准映射CloseToday；金额比例字段为1.2/10000，按金额收费时对应Volume字段为0。",
    )

    # GFEX official notice: 广期所发〔2025〕374号.
    # Effective from 2025-11-24 trading. LC2601 was adjusted to 0.032%;
    # LC2602-LC2605 were adjusted to 0.016%.
    for contract_code, money_ratio, ratio_text in [
        ("2601", 0.00032, "万分之三点二"),
        ("2602", 0.00016, "万分之一点六"),
        ("2603", 0.00016, "万分之一点六"),
        ("2604", 0.00016, "万分之一点六"),
        ("2605", 0.00016, "万分之一点六"),
    ]:
        yield from _contract_money_fee_events(
            data_source="GFEX",
            source_url="https://www.gfex.com.cn/gfex/tzts/202511/",
            source_notice_id="广期所发〔2025〕374号",
            instrument="LC",
            instrument_label="碳酸锂",
            effective_trading_day="2025-11-24",
            effective_timestamp="",
            contract_code=contract_code,
            money_ratio=money_ratio,
            raw_note=(
                "自2025年11月24日交易时起，碳酸锂期货LC2601合约的交易手续费标准和日内平今仓交易手续费标准调整为成交金额的万分之三点二，"
                "LC2602、LC2603、LC2604、LC2605合约调整为成交金额的万分之一点六。"
            ),
            evidence_text=f"LC{contract_code}合约；交易手续费标准和日内平今仓交易手续费标准；成交金额的{ratio_text}。",
            parser_notes="交易手续费标准映射开仓/普通平仓，日内平今仓交易手续费标准映射CloseToday；按金额收费时对应Volume字段为0。",
        )

    # SHFE official notice: 上期发〔2026〕3号.
    # Effective from 2026-01-09 trading, i.e. 2026-01-08 night session.
    yield from _contract_close_today_money_events(
        data_source="SHFE",
        source_url="https://www.shfe.com.cn/news/notice/911406071.html",
        source_notice_id="上期发〔2026〕3号",
        instrument="AG",
        instrument_label="白银",
        effective_trading_day="2026-01-09",
        effective_timestamp="2026-01-08 21:00:00",
        contract_code="2604",
        money_ratio=0.00025,
        raw_note="自2026年1月9日交易（即1月8日晚夜盘）起，白银期货AG2604合约日内平今仓交易手续费调整为成交金额的万分之二点五。",
        evidence_text="白银期货AG2604合约；日内平今仓交易手续费；成交金额的万分之二点五。",
        parser_notes="公告只调整平今仓字段；按金额收费时CloseTodayRatioByVolume为0。",
    )
    yield from _contract_close_today_volume_events(
        data_source="SHFE",
        source_url="https://www.shfe.com.cn/news/notice/911406071.html",
        source_notice_id="上期发〔2026〕3号",
        instrument="SN",
        instrument_label="锡",
        effective_trading_day="2026-01-09",
        effective_timestamp="2026-01-08 21:00:00",
        contract_code="2602",
        volume_fee=15.0,
        raw_note="自2026年1月9日交易（即1月8日晚夜盘）起，锡期货SN2602合约日内平今仓交易手续费调整为15元/手。",
        evidence_text="锡期货SN2602合约；日内平今仓交易手续费；15元/手。",
        parser_notes="公告只调整平今仓字段；按手数收费时CloseTodayRatioByMoney为0。",
    )


def _contract_money_fee_events(
    *,
    data_source: str,
    source_url: str,
    source_notice_id: str,
    instrument: str,
    instrument_label: str,
    effective_trading_day: str,
    effective_timestamp: str,
    contract_code: str,
    money_ratio: float,
    raw_note: str,
    evidence_text: str,
    parser_notes: str,
) -> Iterable[dict[str, Any]]:
    for field_name, value in [
        ("OpenRatioByMoney", money_ratio),
        ("CloseRatioByMoney", money_ratio),
        ("CloseTodayRatioByMoney", money_ratio),
        ("OpenRatioByVolume", 0.0),
        ("CloseRatioByVolume", 0.0),
        ("CloseTodayRatioByVolume", 0.0),
    ]:
        yield _event(
            data_source=data_source,
            source_url=source_url,
            source_notice_id=source_notice_id,
            instrument=instrument,
            instrument_label=instrument_label,
            field_name=field_name,
            effective_trading_day=effective_trading_day,
            effective_timestamp=effective_timestamp,
            value=value,
            contract_code=contract_code,
            raw_note=raw_note,
            evidence_text=evidence_text,
            parser_notes=parser_notes,
        )


def _contract_close_today_money_events(
    *,
    data_source: str,
    source_url: str,
    source_notice_id: str,
    instrument: str,
    instrument_label: str,
    effective_trading_day: str,
    effective_timestamp: str,
    contract_code: str,
    money_ratio: float,
    raw_note: str,
    evidence_text: str,
    parser_notes: str,
) -> Iterable[dict[str, Any]]:
    for field_name, value in [
        ("CloseTodayRatioByMoney", money_ratio),
        ("CloseTodayRatioByVolume", 0.0),
    ]:
        yield _event(
            data_source=data_source,
            source_url=source_url,
            source_notice_id=source_notice_id,
            instrument=instrument,
            instrument_label=instrument_label,
            field_name=field_name,
            effective_trading_day=effective_trading_day,
            effective_timestamp=effective_timestamp,
            value=value,
            contract_code=contract_code,
            raw_note=raw_note,
            evidence_text=evidence_text,
            parser_notes=parser_notes,
        )


def _contract_close_today_volume_events(
    *,
    data_source: str,
    source_url: str,
    source_notice_id: str,
    instrument: str,
    instrument_label: str,
    effective_trading_day: str,
    effective_timestamp: str,
    contract_code: str,
    volume_fee: float,
    raw_note: str,
    evidence_text: str,
    parser_notes: str,
) -> Iterable[dict[str, Any]]:
    for field_name, value in [
        ("CloseTodayRatioByMoney", 0.0),
        ("CloseTodayRatioByVolume", volume_fee),
    ]:
        yield _event(
            data_source=data_source,
            source_url=source_url,
            source_notice_id=source_notice_id,
            instrument=instrument,
            instrument_label=instrument_label,
            field_name=field_name,
            effective_trading_day=effective_trading_day,
            effective_timestamp=effective_timestamp,
            value=value,
            contract_code=contract_code,
            raw_note=raw_note,
            evidence_text=evidence_text,
            parser_notes=parser_notes,
        )


def _event(
    *,
    data_source: str,
    source_url: str,
    source_notice_id: str,
    instrument: str,
    instrument_label: str,
    field_name: str,
    effective_trading_day: str,
    effective_timestamp: str,
    value: float,
    contract_code: str,
    raw_note: str,
    evidence_text: str,
    parser_notes: str,
) -> dict[str, Any]:
    base = {
        "data_source": data_source,
        "field_group": FIELD_GROUP,
        "source_url": source_url,
        "source_accessed_at": SOURCE_ACCESSED_AT,
        "agent_name": AGENT_NAME,
        "requester_key": REQUESTER_KEY,
        "instrument": instrument,
        "instrument_label": instrument_label,
        "instrument_type": "future",
        "field_name": field_name,
        "effective_trading_day": effective_trading_day,
        "effective_timestamp": effective_timestamp,
        "value": value,
        "contract_codes": [contract_code],
        "source_notice_id": source_notice_id,
        "raw_note": raw_note,
        "evidence_text": evidence_text,
        "parser_notes": parser_notes,
    }
    base["event_id"] = _stable_event_id(base)
    return base


def _stable_event_id(event: dict[str, Any]) -> str:
    parts = [
        event["data_source"],
        event["source_notice_id"],
        event["instrument"],
        event["instrument_type"],
        event["field_name"],
        event["effective_trading_day"],
        event["effective_timestamp"],
        ",".join(event["contract_codes"]),
        str(event["value"]),
    ]
    return "transaction_fee_" + sha1("|".join(parts).encode("utf-8")).hexdigest()[:24]


def _event_exists(conn: sqlite3.Connection, event: dict[str, Any]) -> bool:
    if conn.execute(
        f"SELECT 1 FROM {AGENT_EVENT_TABLE} WHERE event_id = ? LIMIT 1",
        (event["event_id"],),
    ).fetchone():
        return True
    contract_codes_json = json.dumps(event["contract_codes"], ensure_ascii=False)
    existing = conn.execute(
        f"""
        SELECT 1
        FROM {HISTORICAL_FIELD_TABLE}
        WHERE instrument = ?
          AND instrument_type = ?
          AND field_name = ?
          AND effective_trading_day = ?
          AND COALESCE(effective_timestamp, '') = COALESCE(?, '')
          AND contract_codes = ?
          AND value = ?
        LIMIT 1
        """,
        (
            event["instrument"],
            event["instrument_type"],
            event["field_name"],
            event["effective_trading_day"],
            event["effective_timestamp"],
            contract_codes_json,
            json.dumps(event["value"], ensure_ascii=False),
        ),
    ).fetchone()
    return existing is not None


if __name__ == "__main__":
    raise SystemExit(main())
