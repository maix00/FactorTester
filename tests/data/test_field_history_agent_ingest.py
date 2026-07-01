from __future__ import annotations

import json

import pandas as pd

from tools.data.field_history import FieldHistoryProvider, TimestampTradingDayResolver, load_historical_field_frame
from tools.data.field_history_agent_ingest import (
    AGENT_EVENT_TABLE,
    append_agent_field_change_events,
    materialize_agent_events_to_history,
)
from tools.data.hub import DataHub, SQLiteStore


def test_agent_field_change_ingest_hashes_requester_key_and_materializes(tmp_path) -> None:
    db_path = tmp_path / "agent_ingest.sqlite"
    store_key = "agent_ingest_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="agent-ingest-test",
        path_getter=lambda: str(db_path),
    ))

    event_ids = append_agent_field_change_events(
        [
            {
                "data_source": "DCE",
                "field_group": "LimitOrderVolume",
                "source_url": "http://www.dce.com.cn/dce/content/2026/ywggytz/18627837.html",
                "source_accessed_at": "2026-06-29T12:00:00+08:00",
                "agent_name": "codex-test",
                "requester_key": "human-secret-key",
                "instrument": "BZ",
                "instrument_label": "纯苯",
                "instrument_type": "future",
                "field_name": "MinLimitOrderVolume",
                "effective_trading_day": "2026-03-10",
                "effective_timestamp": "2026-03-09 21:00:00",
                "value": 4,
                "contract_codes": ["2604"],
                "source_notice_id": "大商所发〔2026〕74号",
                "raw_note": "纯苯期货BZ2604、BZ2605、BZ2606合约交易指令每次最小开仓下单数量调整为4手",
                "evidence_text": "BZ2604、BZ2605、BZ2606 ... 4手",
                "parser_notes": "Parsed contract tokens and split the source sentence into one event per contract.",
            }
        ],
        store_key=store_key,
    )

    assert len(event_ids) == 1
    with DataHub.get_instance().connect_store(store_key) as conn:
        row = conn.execute(f"SELECT * FROM {AGENT_EVENT_TABLE}").fetchone()
        assert row["requester_key_hash"].startswith("hmac-sha256-v1:")
        assert "human-secret-key" not in json.dumps(dict(row), ensure_ascii=False)

    assert materialize_agent_events_to_history(store_key=store_key) == 1
    history = load_historical_field_frame(store_key=store_key)
    provider = FieldHistoryProvider(history)
    value = provider.resolve_at(
        "BZ2604.DCE",
        "MinLimitOrderVolume",
        pd.Timestamp("2026-03-10 09:01:00"),
        trading_day_resolver=TimestampTradingDayResolver({
            pd.Timestamp("2026-03-10 09:01:00"): pd.Timestamp("2026-03-10"),
        }),
    )

    assert value.value == 4
    assert value.provider == "Agent:DCE"
    assert value.source_key == f"agent/DCE/{event_ids[0]}"


def test_agent_field_change_ingest_rejects_multi_contract_event(tmp_path) -> None:
    db_path = tmp_path / "agent_ingest_reject.sqlite"
    store_key = "agent_ingest_reject_test"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label="agent-ingest-reject-test",
        path_getter=lambda: str(db_path),
    ))

    try:
        append_agent_field_change_events(
            [
                {
                    "data_source": "DCE",
                    "field_group": "LimitOrderVolume",
                    "source_url": "http://www.dce.com.cn/dce/content/2026/ywggytz/18627837.html",
                    "source_accessed_at": "2026-06-29T12:00:00+08:00",
                    "agent_name": "codex-test",
                    "requester_key": "human-secret-key",
                    "instrument": "BZ",
                    "instrument_label": "纯苯",
                    "instrument_type": "future",
                    "field_name": "MinLimitOrderVolume",
                    "effective_trading_day": "2026-03-10",
                    "effective_timestamp": "2026-03-09 21:00:00",
                    "value": 4,
                    "contract_codes": ["2604", "2605", "2606"],
                    "source_notice_id": "大商所发〔2026〕74号",
                    "raw_note": "纯苯期货BZ2604、BZ2605、BZ2606合约交易指令每次最小开仓下单数量调整为4手",
                }
            ],
            store_key=store_key,
        )
    except ValueError as exc:
        assert "one event per contract" in str(exc)
    else:
        raise AssertionError("multi-contract agent event should be rejected")
