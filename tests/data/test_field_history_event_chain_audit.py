from __future__ import annotations

from collections import Counter

import pandas as pd

from sources.FieldHistory.scripts.backfill_effective_timestamps import _timestamp_for_session
from sources.FieldHistory.scripts.audit_field_history_event_chain import audit_event_chain
from tools.data.field_history_agent_ingest import append_agent_field_change_events
from tools.data.hub import DataHub, SQLiteStore


def _register_store(tmp_path, name: str) -> str:
    store_key = f"event_chain_{name}"
    db_path = tmp_path / f"{name}.sqlite"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key=store_key,
        label=store_key,
        path_getter=lambda: str(db_path),
    ))
    return store_key


def _event(**overrides):
    base = {
        "data_source": "CZCE",
        "field_group": "TransactionFee",
        "source_url": "https://www.czce.com.cn/test.pdf",
        "source_accessed_at": "2026-07-09T00:00:00+08:00",
        "agent_name": "codex-test",
        "requester_key": "human-secret-key",
        "instrument": "X",
        "instrument_label": "测试",
        "instrument_type": "future",
        "scope_type": "product",
        "exchange": "CZCE",
        "field_name": "OpenRatioByVolume",
        "effective_trading_day": "2024-01-02",
        "effective_timestamp": "2024-01-02 09:00:00",
        "value": 3.0,
        "contract_scope_type": "all",
        "change_type": "change",
        "source_notice_id": "notice-a",
    }
    base.update(overrides)
    return base


def test_event_chain_flags_change_repeating_prior_asof(tmp_path) -> None:
    store_key = _register_store(tmp_path, "change_repeats_asof")
    append_agent_field_change_events(
        [
            _event(
                event_id="asof",
                effective_trading_day="2024-01-02",
                change_type="asof_confirmed",
                source_notice_id="snapshot-20240102",
            ),
            _event(
                event_id="change",
                effective_trading_day="2024-01-03",
                source_notice_id="notice-a",
            ),
        ],
        store_key=store_key,
    )

    issues = audit_event_chain(store_key=store_key, asof_day="2024-01-02")

    assert Counter(issue["status"] for issue in issues) == {"duplicate_non_asof_value": 1}


def test_event_chain_does_not_flag_far_apart_different_notice_same_value(tmp_path) -> None:
    store_key = _register_store(tmp_path, "far_same_value")
    append_agent_field_change_events(
        [
            _event(event_id="old", effective_trading_day="2024-01-02", source_notice_id="notice-a"),
            _event(
                event_id="new",
                effective_trading_day="2024-03-15",
                source_notice_id="notice-b",
                source_url="https://www.czce.com.cn/other.pdf",
            ),
        ],
        store_key=store_key,
    )

    assert audit_event_chain(store_key=store_key, asof_day="2024-01-02") == []


def test_event_chain_previous_value_different_is_not_duplicate(tmp_path) -> None:
    store_key = _register_store(tmp_path, "previous_value_differs")
    append_agent_field_change_events(
        [
            _event(event_id="old", effective_trading_day="2024-01-02", value=3.0, source_notice_id="notice-a"),
            _event(
                event_id="new",
                effective_trading_day="2024-01-03",
                value=3.0,
                previous_value=2.0,
                source_notice_id="notice-b",
                source_url="https://www.czce.com.cn/other.pdf",
            ),
        ],
        store_key=store_key,
    )

    assert audit_event_chain(store_key=store_key, asof_day="2024-01-02") == []


def test_event_chain_flags_same_source_same_value(tmp_path) -> None:
    store_key = _register_store(tmp_path, "same_source_same_value")
    append_agent_field_change_events(
        [
            _event(event_id="old", effective_trading_day="2024-01-02", source_notice_id="notice-a"),
            _event(event_id="new", effective_trading_day="2024-01-10", source_notice_id="notice-a"),
        ],
        store_key=store_key,
    )

    issues = audit_event_chain(store_key=store_key, asof_day="2024-01-02")

    assert Counter(issue["status"] for issue in issues) == {"duplicate_non_asof_value": 1}


def test_event_chain_flags_same_day_duplicate_values(tmp_path) -> None:
    store_key = _register_store(tmp_path, "same_day_duplicate")
    append_agent_field_change_events(
        [
            _event(event_id="official", source_notice_id="notice-a", value=3.0),
            _event(event_id="duplicate", source_notice_id="", value=3.0),
        ],
        store_key=store_key,
    )

    issues = audit_event_chain(store_key=store_key, asof_day="2024-01-02")

    assert Counter(issue["status"] for issue in issues) == {"same_day_duplicate_value": 1}


def test_event_chain_flags_same_day_conflicting_values(tmp_path) -> None:
    store_key = _register_store(tmp_path, "same_day_conflict")
    append_agent_field_change_events(
        [
            _event(event_id="official", source_notice_id="notice-a", value=3.0),
            _event(event_id="conflict", source_notice_id="notice-b", value=4.0),
        ],
        store_key=store_key,
    )

    issues = audit_event_chain(store_key=store_key, asof_day="2024-01-02")

    assert Counter(issue["status"] for issue in issues) == {"same_day_conflicting_values": 1}


def test_event_chain_requires_effective_trading_day_and_timestamp(tmp_path) -> None:
    store_key = _register_store(tmp_path, "missing_effective_time")
    append_agent_field_change_events(
        [
            _event(event_id="missing_ts", effective_timestamp=""),
        ],
        store_key=store_key,
    )

    issues = audit_event_chain(store_key=store_key, asof_day="2024-01-02")

    assert Counter(issue["status"] for issue in issues) == {"missing_effective_datetime": 1}


def test_backfill_night_session_uses_previous_trading_day_not_calendar_day() -> None:
    trading_days = pd.DatetimeIndex([
        pd.Timestamp("2026-06-05"),
        pd.Timestamp("2026-06-08"),
    ])

    assert _timestamp_for_session(
        "2026-06-08",
        "night",
        trading_days=trading_days,
        data_source="CZCE",
    ) == "2026-06-05 21:00:00"
