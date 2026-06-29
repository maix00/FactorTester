from __future__ import annotations

import json

import pandas as pd
from tools.data.hub import DataHub, SQLiteStore

from sources.ExchangeAnnouncements.LimitOrderVolume.DCE.MinLimitOrderVolume import (
    iter_historical_field_records,
)
from sources.ExchangeAnnouncements.field_announcements import (
    ANNOUNCEMENT_TABLE,
    discover_and_sync_field_announcements,
    get_exchange_announcement_adapter,
)
from sources.FieldHistory.LimitOrderVolume import build_unified_frame, build_unified_provider
from tools.data.field_history import TimestampTradingDayResolver


def test_dce_official_notice_keeps_delisted_contract_scope() -> None:
    records = list(iter_historical_field_records())
    bz = [row for row in records if row["instrument"] == "BZ"]

    assert len(bz) == 1
    assert bz[0]["contract_codes"] == ["2604", "2605", "2606"]
    assert bz[0]["source_notice_id"] == "大商所发〔2026〕74号"
    assert bz[0]["effective_trading_day"] == "2026-03-10"
    assert bz[0]["effective_timestamp"] == "2026-03-09 21:00:00"
    assert bz[0]["value"] == 4


def test_limit_order_volume_unified_frame_cross_references_sources() -> None:
    frame = pd.DataFrame([
        {
            "provider": "Guosen",
            "source_key": "Guosen/LimitOrderVolume",
            "instrument": "BZ",
            "instrument_label": "纯苯",
            "instrument_type": "future",
            "field_name": "MinLimitOrderVolume",
            "effective_trading_day": "2026-03-10",
            "effective_timestamp": "2026-03-09 21:00:00",
            "value": "4",
            "value_type": "int",
            "contract_codes": json.dumps(["2604", "2605", "2606"]),
            "source_url": "https://guosen.example/rules",
            "source_date": "2026-06-23",
            "source_notice_id": "",
            "raw_note": "Guosen snapshot",
        },
        {
            "provider": "DCE",
            "source_key": "DCE/LimitOrderVolume/MinLimitOrderVolume",
            "instrument": "BZ",
            "instrument_label": "纯苯",
            "instrument_type": "future",
            "field_name": "MinLimitOrderVolume",
            "effective_trading_day": "2026-03-10",
            "effective_timestamp": "2026-03-09 21:00:00",
            "value": "4",
            "value_type": "int",
            "contract_codes": json.dumps(["2606", "2605", "2604"]),
            "source_url": "http://www.dce.com.cn/dce/content/2026/ywggytz/18627837.html",
            "source_date": "2026-03-09",
            "source_notice_id": "大商所发〔2026〕74号",
            "raw_note": "DCE notice",
        },
    ])

    unified = build_unified_frame(frame)

    assert len(unified) == 1
    row = unified.iloc[0]
    assert row["source_count"] == 2
    assert json.loads(row["providers"]) == ["DCE", "Guosen"]
    assert json.loads(row["source_notice_ids"]) == ["大商所发〔2026〕74号"]


def test_limit_order_volume_unified_provider_resolves_contract_scope() -> None:
    source_frame = pd.DataFrame(list(iter_historical_field_records()))
    provider = build_unified_provider(build_unified_frame(source_frame))

    value = provider.resolve_at(
        "BZ2604.DCE",
        "MinLimitOrderVolume",
        pd.Timestamp("2026-03-10 09:01:00"),
        trading_day_resolver=TimestampTradingDayResolver({
            pd.Timestamp("2026-03-10 09:01:00"): pd.Timestamp("2026-03-10"),
        }),
    )

    assert value.value == 4
    assert value.contract_code == "2604"


def test_public_announcement_helper_discovers_and_syncs_dce_rules(tmp_path) -> None:
    db_path = tmp_path / "field_announcements.sqlite"
    DataHub.get_instance().register_sqlite_store(SQLiteStore(
        key="announcement_helper_test",
        label="announcement-helper-test",
        path_getter=lambda: str(db_path),
    ))

    summary = discover_and_sync_field_announcements(
        "BZ.DCE",
        "MinLimitOrderVolume",
        store_key="announcement_helper_test",
    )

    assert summary["candidate_count"] == 1
    assert summary["record_count"] == 1
    with DataHub.get_instance().connect_store("announcement_helper_test") as conn:
        announcement = conn.execute(
            f"SELECT * FROM {ANNOUNCEMENT_TABLE} WHERE product_code='BZ'"
        ).fetchone()
        assert announcement is not None
        assert announcement["status"] == "parsed"
        rows = conn.execute(
            """
            SELECT instrument, field_name, value, contract_codes, source_notice_id
            FROM historical_field_values
            WHERE provider='DCE' AND instrument='BZ'
            """
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["source_notice_id"] == "大商所发〔2026〕74号"
        assert json.loads(rows[0]["contract_codes"]) == ["2604", "2605", "2606"]


def test_default_exchange_announcement_adapters_are_registered() -> None:
    for exchange in ("DCE", "SHFE", "INE", "CZCE", "CFFEX", "GFEX"):
        adapter = get_exchange_announcement_adapter(exchange)
        assert adapter.exchange == exchange
